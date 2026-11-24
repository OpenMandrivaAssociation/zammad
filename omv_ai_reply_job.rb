# Optional. Runs /usr/libexec/zammad/ai-reply for a new customer article and,
# when the script returns a reply, posts it on the same channel.
class OmvAIReplyJob < ApplicationJob
  SCRIPT = '/usr/libexec/zammad/ai-reply'.freeze
  CONF = '/etc/zammad/ai-reply.conf'.freeze

  class ScriptError < StandardError; end

  retry_on StandardError, attempts: 3, wait: 30.seconds

  def self.enqueue_for(article)
    return if !enabled?

    prefs = article.preferences
    return if prefs && prefs['omv_ai_reply']
    return if article.internal
    return if Setting.get('import_mode')

    sender = Ticket::Article::Sender.lookup(id: article.sender_id)
    return if sender.nil? || sender.name != 'Customer'

    type = Ticket::Article::Type.lookup(id: article.type_id)
    return if type.nil? || reply_type_for(type.name).nil?

    perform_later(article.id)
  rescue StandardError => e
    Rails.logger.error("omv ai reply: enqueue failed for article #{article.id}: #{e.class}: #{e.message}")
  end

  def self.enabled?
    %w[1 true yes on].include?(read_conf['ENABLED'].to_s.downcase)
  end

  def self.reply_type_for(type_name)
    case type_name
    when 'email', 'sms', 'whatsapp message'
      type_name
    when /\Atelegram/i, /\Afacebook/i
      type_name
    when 'web'
      'email'
    end
  end

  def self.read_conf
    return {} if !File.readable?(CONF)

    File.readlines(CONF, chomp: true).each_with_object({}) do |line, cfg|
      line = line.strip
      next if line.empty? || line.start_with?('#') || !line.include?('=')

      key, value = line.split('=', 2)
      value = unquote(value.strip)
      cfg[key.strip] = value
    end
  rescue StandardError
    {}
  end

  def self.unquote(value)
    return value if value.length < 2

    if (value.start_with?('"') && value.end_with?('"')) ||
       (value.start_with?("'") && value.end_with?("'"))
      return value[1..-2]
    end

    value
  end

  def perform(article_id)
    user_set = false
    article = Ticket::Article.find_by(id: article_id)
    return if article.nil?
    return if already_replied?(article)

    ticket = article.ticket
    return if ticket.nil?

    type_name = article.type&.name
    reply_type = self.class.reply_type_for(type_name)
    if reply_type.nil?
      Rails.logger.info("omv ai reply: no outbound channel for #{type_name} on article #{article.id}")
      return
    end

    recipient = recipient_for(type_name, article, ticket)
    if recipient_required?(reply_type) && recipient.blank?
      Rails.logger.info("omv ai reply: no recipient for article #{article.id}")
      return
    end
    if reply_type == 'email' && ticket.group&.email_address.blank?
      Rails.logger.info("omv ai reply: group #{ticket.group_id} has no email address, article #{article.id}")
      return
    end

    result = run_script(article, ticket, type_name)
    if result['action'] != 'reply'
      Rails.logger.info("omv ai reply: skip article #{article.id}: #{result['reason']}")
      return
    end
    return if result['body'].blank?
    return if already_replied?(article)

    previous_state_id = ticket.state_id
    previous_user_id = UserInfo.current_user_id
    user_set = true
    UserInfo.current_user_id = 1
    Ticket::Article.create!(
      ticket_id:    ticket.id,
      type_id:      Ticket::Article::Type.lookup(name: reply_type).id,
      sender_id:    Ticket::Article::Sender.lookup(name: 'Agent').id,
      body:         result['body'].to_s.first(20_000),
      content_type: 'text/plain',
      internal:     false,
      subject:      ticket.title,
      to:           recipient,
      in_reply_to:  article.message_id,
      preferences:  {
        'omv_ai_reply'      => true,
        'omv_ai_reply_for'  => article.id,
        'omv_ai_confidence' => result['confidence'],
      },
    )
    restore_state(ticket, previous_state_id)
  ensure
    UserInfo.current_user_id = previous_user_id if user_set
  end

  private

  def already_replied?(article)
    Ticket::Article.where(ticket_id: article.ticket_id).any? do |other|
      other.preferences&.[]('omv_ai_reply_for').to_s == article.id.to_s
    end
  end

  def recipient_required?(reply_type)
    reply_type == 'email' || reply_type == 'sms'
  end

  def recipient_for(type_name, article, ticket)
    case type_name
    when 'email', 'web'
      email_to(article, ticket)
    when 'sms'
      article.from.presence
    end
  end

  def email_to(article, ticket)
    email = ticket.customer&.email
    return email if email.present?

    from = article.from.to_s
    match = from.match(/<([^>]+)>/)
    address = match ? match[1] : from
    address.presence
  end

  def run_script(article, ticket, type_name)
    unless File.executable?(SCRIPT)
      raise ScriptError, "#{SCRIPT} is missing"
    end

    payload = JSON.generate(
      ticket_id:     ticket.id,
      ticket_number: ticket.number,
      article_id:    article.id,
      channel:       type_name,
      subject:       ticket.title.to_s,
      customer_name: ticket.customer&.fullname.to_s,
      body:          plain_text(article.body).first(8_000),
    )
    timeout = (self.class.read_conf['TIMEOUT'].presence || 60).to_i + 5
    stdout, stderr, status = capture_script(payload, timeout)
    unless status.success?
      detail = stderr.to_s.strip
      detail = stdout.to_s.strip if detail.empty?
      raise ScriptError, "script failed for article #{article.id}: #{detail.first(500)}"
    end

    JSON.parse(stdout)
  rescue JSON::ParserError => e
    raise ScriptError, "script returned invalid JSON for article #{article.id}: #{e.message}"
  end

  def capture_script(payload, timeout)
    require 'open3'

    env = ENV.to_h.merge('PYTHONDONTWRITEBYTECODE' => '1')
    Open3.popen3(env, SCRIPT) do |stdin, stdout, stderr, wait_thr|
      out = +''
      err = +''
      readers = [
        Thread.new { out = stdout.read.to_s },
        Thread.new { err = stderr.read.to_s },
      ]
      stdin.write(payload)
      stdin.close
      unless wait_thr.join(timeout)
        stop_process(wait_thr.pid)
        wait_thr.join(2)
        stop_process(wait_thr.pid, 'KILL') if wait_thr.alive?
        wait_thr.join(2)
        readers.each { |thread| thread.join(1) }
        raise ScriptError, "script timed out for article"
      end
      readers.each(&:join)
      [out, err, wait_thr.value]
    end
  end

  def stop_process(pid, signal = 'TERM')
    Process.kill(signal, pid)
  rescue Errno::ESRCH
    nil
  end

  def plain_text(body)
    text = ActionController::Base.helpers.strip_tags(body.to_s)
    CGI.unescapeHTML(text).gsub(/[ \t]+/, ' ').gsub(/\n{3,}/, "\n\n").strip
  end

  def restore_state(ticket, state_id)
    ticket.reload
    return if ticket.state_id == state_id

    ticket.update!(state_id: state_id)
  rescue StandardError => e
    Rails.logger.error("omv ai reply: could not restore state of ticket #{ticket.id}: #{e.message}")
  end
end
