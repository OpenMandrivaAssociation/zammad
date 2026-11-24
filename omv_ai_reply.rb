# Optional automatic reply. Does nothing until /etc/zammad/ai-reply.conf
# sets ENABLED=1. The background worker runs OmvAIReplyJob.

Rails.application.config.to_prepare do
  next if Ticket::Article.respond_to?(:_omv_ai_reply_hook)

  Ticket::Article.class_eval do
    def self._omv_ai_reply_hook
      true
    end

    after_create_commit :omv_ai_reply_enqueue

    def omv_ai_reply_enqueue
      OmvAIReplyJob.enqueue_for(self)
    end
    private :omv_ai_reply_enqueue
  end
end
