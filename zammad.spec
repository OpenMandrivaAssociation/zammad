%global __provides_exclude_from ^/srv/www/zammad/.*$
%undefine _debugsource_packages
%global debug_package %{nil}

Summary:	Helpdesk and customer support
Name:		zammad
Version:	7.2.3
Release:	2
License:	AGPL-3.0-only
Group:		Applications/Productivity
URL:		https://zammad.org/
# GitHub archive extracts as zammad-%%{version}/. The #/ suffix is the
# lookaside basename.
Source0:	https://github.com/zammad/zammad/archive/refs/tags/%{version}.tar.gz#/zammad-%{version}.tar.gz
# vendor/cache, including the git gems (autodiscover, delayed_job,
# delayed_job_active_record) and the readline gem added by the patch.
# Produced with cache_all and force_ruby_platform. Native extensions are
# compiled here; vendor/bundle from the packager is not shipped.
Source1:	zammad-%{version}-gems.tar.xz
# public/assets from a production assets:precompile. Source maps are
# left out. The assets gem group is not installed: dartsass would download
# a prebuilt dart-sass binary, which we do not want.
Source2:	zammad-%{version}-assets.tar.xz
Source3:	README.install.omv
Source4:	zammad.env
Source5:	zammad-database.yml
Source6:	zammad.service
Source7:	zammad-web.service
Source8:	zammad-websocket.service
Source9:	zammad-worker.service
Source10:	zammad.redis
Source11:	zammad.sysusers
Source12:	zammad.tmpfiles
Source13:	zammad.nginx.conf
Source14:	zammad.apache.conf
Source15:	zammad.bin
Source16:	zammad.logrotate
Source17:	zammad-httpd-wstunnel.conf
# Optional local-model reply. Off until ai-reply.conf sets ENABLED=1.
Source18:	zammad-ai-reply
Source19:	zammad-ai-reply.conf
Source20:	zammad-ai-reply.template
Source21:	omv_ai_reply.rb
Source22:	omv_ai_reply_job.rb
# Ruby 4: Gemfile allowed range, plus readline for pry-remote.
Patch0:		zammad-%{version}-ruby4.patch
# PostgreSQL prereleases report server_version as "19rc2".
Patch1:		zammad-%{version}-pg-prerelease.patch

BuildRequires:	ruby
BuildRequires:	ruby-devel
BuildRequires:	clang
BuildRequires:	make
BuildRequires:	pkgconfig(libxml-2.0)
BuildRequires:	pkgconfig(libxslt)
BuildRequires:	pkgconfig(libpq)
BuildRequires:	pkgconfig(imlib2)
BuildRequires:	pkgconfig(openssl)
BuildRequires:	pkgconfig(zlib)
BuildRequires:	pkgconfig(libffi)

Requires:	ruby >= 4.0.9
Requires:	ruby < 4.1
Requires:	/usr/bin/python
Requires:	postgresql-server
Requires:	redis
Requires:	zammad-webserver-integration = %{EVRD}
Recommends:	gnupg
Requires(post):	systemd
Requires(post):	postgresql-server
Requires(post):	redis

%description
Zammad is a web helpdesk for tickets, email, and chat.

It is installed under /srv/www/zammad and uses PostgreSQL and a private
Redis instance on this machine. Elasticsearch is optional and is not
packaged. The setup wizard in the browser creates the administrator.

A new customer message can be passed to a local model, which replies on
the same channel when it is confident enough. That is off until
/etc/zammad/ai-reply.conf sets ENABLED=1. The wording is
/etc/zammad/ai-reply.template.

See README.install.omv after installation.

%package nginx
Summary:	nginx integration for Zammad
Group:		Applications/Productivity
BuildArch:	noarch
Requires:	%{name} = %{EVRD}
Requires:	nginx
Provides:	zammad-webserver-integration = %{EVRD}

%description nginx
nginx site for Zammad. The site is installed disabled. Symlink it into
sites-enabled. It answers names matching zammad.* and proxies to the
local Puma and websocket processes.

%package apache
Summary:	Apache integration for Zammad
Group:		Applications/Productivity
BuildArch:	noarch
Requires:	%{name} = %{EVRD}
Requires:	apache-base
Requires:	apache-mod_proxy
Requires:	apache-mod_proxy_http
Requires:	apache-mod_proxy_wstunnel
Requires:	apache-mod_headers
Provides:	zammad-webserver-integration = %{EVRD}

%description apache
Apache virtual host for Zammad. The file is installed as
zammad.conf.disabled so it is not included automatically. The first
real VirtualHost would become Apache's default server for port 80.

%prep
%autosetup -p1 -n zammad-%{version}
tar -xf %{SOURCE1}
tar -xf %{SOURCE2}

%build
# Keep Bundler out of /root and out of the packager's home.
export HOME=%{_builddir}/zammad-bundle-home
export BUNDLE_USER_HOME="$HOME"
mkdir -p "$HOME"
# Upstream locks Ruby 3.4.12 and Bundler 2.6.9. Rewrite both before
# Bundler runs, or it tries to download that Bundler.
ruby -rbundler << 'RUBY'
lock = File.read("Gemfile.lock")
raise "ruby line missing" unless lock.sub!(/^   ruby .*/, "   ruby #{RUBY_VERSION}p#{RUBY_PATCHLEVEL}")
raise "bundler line missing" unless lock.sub!(/^BUNDLED WITH\n   .*/, "BUNDLED WITH\n   #{Bundler::VERSION}")
File.write("Gemfile.lock", lock)
RUBY
export BUNDLE_WITHOUT=development:test:assets
export BUNDLE_FORCE_RUBY_PLATFORM=true
export BUNDLE_PATH=vendor/bundle
export BUNDLE_CACHE_ALL=true
export BUNDLE_BUILD__NOKOGIRI=--use-system-libraries
export BUNDLE_RETRY=0
export GIT_TERMINAL_PROMPT=0
bundle install --local --jobs=%{_smp_build_ncpus}
rm -rf "$HOME"
nokogiri_so=$(find vendor/bundle -name 'nokogiri.so' | head -n 1)
if [ -z "$nokogiri_so" ] || ! ldd "$nokogiri_so" | grep -q 'libxml2\.so'; then
	echo "nokogiri was not linked against the system libxml2" >&2
	exit 1
fi

%install
install -d %{buildroot}/srv/www/%{name}
cp -a . %{buildroot}/srv/www/%{name}/
app=%{buildroot}/srv/www/%{name}
rm -rf \
	"$app/vendor/cache" \
	"$app/vendor/bundle/ruby/"*/cache \
	"$app/node_modules" \
	"$app/tmp" \
	"$app/log" \
	"$app/storage" \
	"$app/spec" \
	"$app/test" \
	"$app/.github" \
	"$app/.gitlab" \
	"$app/.dev" \
	"$app/.devcontainer" \
	"$app/.claude" \
	"$app/doc/developer_manual" \
	"$app/coverage" \
	"$app/contrib/docker" \
	"$app/contrib/packager.io" \
	"$app/contrib/apache2" \
	"$app/contrib/nginx" \
	"$app/app/frontend/tests" \
	"$app/app/frontend/cypress" \
	"$app/app/assets/javascripts/app/controllers/layout_ref.coffee" \
	"$app/app/assets/javascripts/app/views/layout_ref"
find "$app/app/frontend" -type d -name __tests__ -exec rm -rf {} + || :
find "$app/vendor/bundle" -name .git -type d -prune -exec rm -rf {} + || :
find "$app/public/assets" -name '*.map' -delete || :
# MRI never loads these. Leaving the JRuby jars in makes rpm require a JDK.
find "$app" \( -name '*.jar' -o -name '*.jmod' \) -delete || :
rm -rf "$app/script/systemd"
rm -f \
	"$app/.rspec" \
	"$app/.rubocop.yml" \
	"$app/.stylelintrc.json" \
	"$app/.oxlintrc.json" \
	"$app/eslint.config.ts" \
	"$app/.oxfmtrc.json" \
	"$app/coffeelint.json" \
	"$app/.markdownlint.yml" \
	"$app/.gitleaks.toml" \
	"$app/.yardopts" \
	"$app/AGENTS.md" \
	"$app/.gitlab-ci.yml" \
	"$app/.coderabbit.yml" \
	"$app"/.overcommit.*
find "$app" -type d -exec chmod 0755 {} \;
find "$app" -type f -exec chmod 0644 {} \;
chmod 0755 "$app"/bin/* "$app"/script/*
if [ -n "$(echo "$app"/vendor/bundle/ruby/*/bin/*)" ]; then
	chmod 0755 "$app"/vendor/bundle/ruby/*/bin/* || :
fi
ln -s /var/lib/zammad/storage "$app/storage"
ln -s /var/lib/zammad/tmp "$app/tmp"
ln -s /var/log/zammad "$app/log"
rm -f "$app/config/database.yml"
ln -s %{_sysconfdir}/zammad/database.yml "$app/config/database.yml"
mkdir -p "$app/.bundle"
cat > "$app/.bundle/config" << 'EOF'
---
BUNDLE_PATH: "vendor/bundle"
BUNDLE_WITHOUT: "development:test:assets"
BUNDLE_FORCE_RUBY_PLATFORM: "true"
EOF

install -d %{buildroot}%{_bindir}
install -m 0755 %{SOURCE15} %{buildroot}%{_bindir}/zammad
install -d %{buildroot}%{_unitdir}
install -m 0644 %{SOURCE6} %{buildroot}%{_unitdir}/zammad.service
install -m 0644 %{SOURCE7} %{buildroot}%{_unitdir}/zammad-web.service
install -m 0644 %{SOURCE8} %{buildroot}%{_unitdir}/zammad-websocket.service
install -m 0644 %{SOURCE9} %{buildroot}%{_unitdir}/zammad-worker.service
install -d %{buildroot}%{_sysusersdir}
install -m 0644 %{SOURCE11} %{buildroot}%{_sysusersdir}/zammad.conf
install -d %{buildroot}%{_tmpfilesdir}
install -m 0644 %{SOURCE12} %{buildroot}%{_tmpfilesdir}/zammad.conf
install -d %{buildroot}%{_sysconfdir}/redis
install -m 0644 %{SOURCE10} %{buildroot}%{_sysconfdir}/redis/zammad.conf
install -d %{buildroot}%{_sysconfdir}/zammad
install -m 0640 %{SOURCE5} %{buildroot}%{_sysconfdir}/zammad/database.yml
install -m 0640 %{SOURCE19} %{buildroot}%{_sysconfdir}/zammad/ai-reply.conf
install -m 0644 %{SOURCE20} %{buildroot}%{_sysconfdir}/zammad/ai-reply.template
install -m 0644 %{SOURCE4} %{buildroot}%{_sysconfdir}/zammad/zammad.env
install -d %{buildroot}%{_libexecdir}/zammad
install -m 0755 %{SOURCE18} %{buildroot}%{_libexecdir}/zammad/ai-reply
install -m 0644 %{SOURCE21} %{buildroot}/srv/www/%{name}/config/initializers/omv_ai_reply.rb
install -m 0644 %{SOURCE22} %{buildroot}/srv/www/%{name}/app/jobs/omv_ai_reply_job.rb
install -d %{buildroot}%{_sysconfdir}/logrotate.d
install -m 0644 %{SOURCE16} %{buildroot}%{_sysconfdir}/logrotate.d/zammad
install -d %{buildroot}%{_sysconfdir}/nginx/sites-available
install -m 0644 %{SOURCE13} %{buildroot}%{_sysconfdir}/nginx/sites-available/zammad.conf
install -d %{buildroot}%{_sysconfdir}/httpd/conf/vhosts.d
install -m 0644 %{SOURCE14} %{buildroot}%{_sysconfdir}/httpd/conf/vhosts.d/zammad.conf.disabled
install -d %{buildroot}%{_sysconfdir}/httpd/modules.d
install -m 0644 %{SOURCE17} %{buildroot}%{_sysconfdir}/httpd/modules.d/070_zammad_proxy_wstunnel.conf
cp %{SOURCE3} .

%pre
if [ "$1" -ge 2 ]; then
	systemctl stop zammad.service zammad-web.service zammad-websocket.service zammad-worker.service >/dev/null 2>&1 || :
fi

%post
set -e
set -o pipefail
systemd-sysusers %{_sysusersdir}/zammad.conf
install -d -o zammad -g zammad -m 0750 /var/lib/zammad
install -d -o zammad -g zammad -m 0750 /var/lib/zammad/storage
install -d -o zammad -g zammad -m 0750 /var/lib/zammad/tmp
install -d -o zammad -g zammad -m 0750 /var/lib/zammad/tmp/cache
install -d -o zammad -g zammad -m 0750 /var/lib/zammad/tmp/pids
install -d -o zammad -g zammad -m 0750 /var/lib/zammad/tmp/sockets
install -d -o zammad -g zammad -m 0750 /var/log/zammad
install -d -o redis -g redis -m 0755 /srv/redis/zammad
chgrp zammad %{_sysconfdir}/zammad/database.yml %{_sysconfdir}/zammad/ai-reply.conf
chmod 0640 %{_sysconfdir}/zammad/database.yml %{_sysconfdir}/zammad/ai-reply.conf

systemctl daemon-reload
systemctl enable redis@zammad.service
systemctl enable zammad.service
systemctl start postgresql.service
systemctl start redis@zammad.service

i=0
while [ "$i" -lt 60 ]; do
	if runuser -u postgres -- pg_isready -q; then
		break
	fi
	i=$((i + 1))
	sleep 1
done
if ! runuser -u postgres -- pg_isready -q; then
	echo "zammad: PostgreSQL did not become ready" >&2
	exit 1
fi
i=0
while [ "$i" -lt 30 ]; do
	if [ -S /run/redis/zammad/redis.sock ]; then
		break
	fi
	i=$((i + 1))
	sleep 1
done
if [ ! -S /run/redis/zammad/redis.sock ]; then
	echo "zammad: Redis socket /run/redis/zammad/redis.sock did not appear" >&2
	exit 1
fi

if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='zammad'" | grep -q 1; then
	runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE USER zammad;"
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='zammad_production'" | grep -q 1; then
	runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE zammad_production OWNER zammad ENCODING 'UTF8' TEMPLATE template0;"
fi
runuser -u postgres -- psql -d zammad_production -v ON_ERROR_STOP=1 -c "GRANT ALL ON SCHEMA public TO zammad;"

if [ "$1" -eq 1 ]; then
	/usr/bin/zammad run rake db:migrate db:seed
else
	/usr/bin/zammad run rake db:migrate
	/usr/bin/zammad run rails runner 'Locale.sync; Translation.sync'
fi
systemctl start zammad.service

%postun
if [ "$1" -eq 0 ]; then
	systemctl disable --now zammad.service zammad-web.service zammad-websocket.service zammad-worker.service redis@zammad.service >/dev/null 2>&1 || :
fi

%files
%doc README.install.omv README.md
%license LICENSE LICENSE-3RD-PARTY.txt LICENSE-ICONS-3RD-PARTY.json
%{_bindir}/zammad
%{_unitdir}/zammad.service
%{_unitdir}/zammad-web.service
%{_unitdir}/zammad-websocket.service
%{_unitdir}/zammad-worker.service
%{_sysusersdir}/zammad.conf
%{_tmpfilesdir}/zammad.conf
%config(noreplace) %{_sysconfdir}/redis/zammad.conf
%config(noreplace) %{_sysconfdir}/logrotate.d/zammad
%dir %{_sysconfdir}/zammad
%config(noreplace) %attr(0640,root,root) %verify(not group) %{_sysconfdir}/zammad/database.yml
%config(noreplace) %attr(0640,root,root) %verify(not group) %{_sysconfdir}/zammad/ai-reply.conf
%config(noreplace) %{_sysconfdir}/zammad/ai-reply.template
%config(noreplace) %{_sysconfdir}/zammad/zammad.env
%dir %{_libexecdir}/zammad
%{_libexecdir}/zammad/ai-reply
/srv/www/zammad

%files nginx
%config(noreplace) %{_sysconfdir}/nginx/sites-available/zammad.conf

%files apache
%config(noreplace) %{_sysconfdir}/httpd/conf/vhosts.d/zammad.conf.disabled
%config(noreplace) %{_sysconfdir}/httpd/modules.d/070_zammad_proxy_wstunnel.conf
