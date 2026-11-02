# JobNova on Oracle Cloud (Ubuntu 22.04, 1 CPU, 1 GB, Mumbai)

Your existing Flask site + a new admin page, behind a Cloudflare Tunnel.
Not run end to end in my test environment (syntax-checked only): test on a temporary
subdomain (step 4) BEFORE moving jobnova.net.in.

## Files
- app.py: your app, with small changes (admin panel hook, Cloudflare AI hook, manual posts shown as written, secure cookies)
- admin_panel.py: /admin/ login, list, add, edit, delete posts
- setup.sh: one-command installer (swap, Python, service, daily backup, cloudflared)
- env.example: settings template (becomes /opt/jobnova/.env)
- js_fix.py + js_render.py + install_browser.sh: headless Chrome for pages that build their links with JavaScript
- site_settings.py + site_ui.py + admin_site.py: /admin/site (hide or show buttons and tabs, popup, festival bar, own ad spaces)
- ssl_fix.py: retries old government sites that fail with SSL errors 
- site_ui.py: /admin/site controls (buttons on/off, subscribe popup, special-day buttons, own photo/message ads)
- cf_ai.py: Cloudflare Workers AI with hard daily limits (DAILY_AI_LIMIT, DAILY_POST_LIMIT)
- copy_db.py: copies jobs + subscribers from Render/Aiven into the new database
- requirements.txt: your original list

## Steps
1. GitHub: in your repo, replace app.py and add the other files (keep the same folder). Never upload .env.
2. SSH into the VM (phone: Termius app + your Oracle private key), then:
   git clone https://github.com/YOU/REPO.git /tmp/jn && bash /tmp/jn/setup.sh https://github.com/YOU/REPO.git
   It prints your new admin password and ADMIN_KEY. Save both.
3. Check: sudo systemctl status jobnova   and   curl -I http://127.0.0.1:8000/
4. Cloudflare Zero Trust -> Networks -> Tunnels -> Create tunnel (Cloudflared). Copy the install
   command, run it on the VM (sudo cloudflared service install <TOKEN>). Add a Public hostname:
   test.jobnova.net.in -> HTTP -> localhost:8000. Open it and test the site and /admin/.
5. Copy data (do this soon, Render's free database expires):
   cd /opt/jobnova && venv/bin/python copy_db.py "RENDER_DATABASE_URL" "sqlite:////opt/jobnova/data/jobnova.db"
   sudo systemctl restart jobnova
6. Switch: in Cloudflare DNS delete the old jobnova.net.in (and www) records that point to Render,
   then add the Public hostnames jobnova.net.in and www.jobnova.net.in to the same tunnel.
7. Update the Cloudflare Worker secret ADMIN_KEY to the new key. Copy your other settings
   (Gmail/Brevo, AdSense, API keys) from Render into /opt/jobnova/.env, then: sudo systemctl restart jobnova
8. Turn Render off once everything works.

## Admin
https://jobnova.net.in/admin/ : password is ADMIN_PASSWORD in /opt/jobnova/.env.
New posts publish immediately, email subscribers get them, and the Telegram Worker posts them.

## Updating later
cd /opt/jobnova && git pull && sudo systemctl restart jobnova

## Backups
Daily to /opt/jobnova/backups (14 days). Copy them off the VM sometimes (Google Drive via rclone).

## Not included yet
Headless browser (Playwright) for JavaScript-only sites. Chromium needs ~300-500 MB, so on 1 GB
it must run one source at a time. Add it after the site is stable.

## Cloudflare AI (free daily allowance)
1. dash.cloudflare.com -> AI -> Workers AI -> REST API -> create a Workers AI API token. Copy the token and the Account ID.
2. On the VM add to /opt/jobnova/.env:
   CLOUDFLARE_ACCOUNT_ID=...   CLOUDFLARE_API_TOKEN=...   CLOUDFLARE_MODEL=@cf/meta/llama-3.1-8b-instruct
   DAILY_AI_LIMIT=30   DAILY_POST_LIMIT=20
3. sudo systemctl restart jobnova
4. Usage today: https://YOUR_SITE/api/ai-quota?key=YOUR_ADMIN_KEY
Limits reset at midnight UTC. Hand-written admin posts are never limited.
Free allowances change: check Cloudflare's Workers AI pricing page.

## SSL errors on old government sites
ssl_fix.py retries a site with tolerant HTTPS only after normal HTTPS fails, and only for hosts in SSL_FALLBACK_HOSTS
(default gov.in,nic.in,cdac.in,ibps.in). The certificate is not checked on that retry. Set SSL_FALLBACK_HOSTS= (empty) to switch off.
It cannot help when a site blocks your server's IP address.

## JavaScript pages (headless Chrome)
1. On the VM, as ubuntu:  cd /opt/jobnova && git pull && bash install_browser.sh   (takes 5-10 minutes, needs ~1 GB disk)
2. Test one source:  /api/source-debug?key=YOUR_ADMIN_KEY&name=SSC&render=1
   It shows how many links the normal fetch sees and how many Chrome sees.
Chrome is used only when a source gives no links, or a notice page gives almost no text. One page at a time,
skipped when free memory is under JS_MIN_FREE_MB (250), at most JS_RENDER_DAILY_LIMIT (40) pages a day. It uses the
same honest bot name and respects robots.txt. It does not get past sites that block your server (403).

## Site controls (/admin/site)
Open Admin, then "Site settings". Everything saves at once and shows on the site straight away.
- Buttons: Log in (hidden by default), every menu tab (Show / Hide / Auto = hide while empty), subscribe bar,
  email signup card, WhatsApp and Telegram buttons, floating WhatsApp, share buttons, empty home sections,
  plus a box for any other link address to hide.
- Popup: subscribe popup when the site opens (on/off, seconds before it shows, days before it shows again).
- Special days: a button that shows only between two dates (tick "every year" for fixed days like 15 August).
- My ads: a photo or a message at the top, the bottom, or inside posts, with optional start and end dates.
Settings are saved in /opt/jobnova/data/site_ui.json and photos in /opt/jobnova/data/uploads/.
Add the same two backup lines that setup.sh now has to /opt/jobnova/backup.sh on an existing server.

## Site settings page (/admin/site)
Log in to /admin/ and tap "Site settings". Everything is saved in the database (the nightly backup covers it) and shows within about 10 seconds.
- Buttons and bars: 9 switches (log in link is OFF by default, subscribe bar and box, Telegram and WhatsApp buttons, share buttons, closing soon strip, apply button).
- Menu tabs: untick any tab, or let tabs with no posts hide themselves. Home always stays.
- Subscribe popup: on/off, delay in seconds, days before it shows again, title and message.
- Festival messages: fixed days repeat every year (08-13 to 08-16). Moving festivals need this year's dates written 2026-11-08.
- Own ad spaces: top, side column (post pages), bottom. Photo (checked, resized, stored in the database), message, link, "Advertisement" label.
If Cloudflare caches your HTML pages, purge the cache after changing settings. By default Cloudflare does not cache HTML.

## Posting by hand (no bot)
The automatic bot is OFF by default: /admin/site -> "Automatic bot". While it is off nothing is read from other websites and no AI is used.
The 3-hourly job still e-mails subscribers about your own posts, and the Telegram Worker still posts them.
## Menu tabs
/admin/site -> "Menu tabs": untick a tab to remove it from the menu, or add up to 8 tabs of your own
(a name plus a link such as /about or https://..., or just a word to search for, such as SSC). Clear both boxes to delete a tab.
