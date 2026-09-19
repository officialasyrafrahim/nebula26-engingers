# Local Public Hosting

Expose the Compose stack to judges through a public tunnel or a private overlay
network. Findings come from official provider documentation and official source
repositories. Commands are tailored to the existing frontend on
`127.0.0.1:5173`.

## What is local

`deploy/docker-compose.yml` binds the UI to `127.0.0.1:5173`. nginx serves the
built SPA and proxies `/api` and `/healthz` to the `api` service on the same
origin. nginx is the only surface that needs ingress. The database and Redis
ports stay on loopback.

The app has no production authentication. It uses a development role header
stub and defaults to the planner role. Any public URL needs an identity or
password gate in front of nginx. Do not rely on the app for access control.

The SPA uses relative `/api/v1` and `/healthz` paths by default and uses no SSE
or WebSocket (`frontend/src/api/client.ts`). Any HTTP tunnel carries the whole
judge flow.

## Public ingress versus private overlay

These are different access models. Keep them separate when choosing.

- Public ingress. The provider gives an internet reachable URL. A judge opens
  the link in a browser and installs nothing. Anyone with the link can reach
  nginx unless the provider adds a visitor gate.
- Private overlay. The provider builds an encrypted peer network. A judge must
  join the network with a client. The service is not on the public internet.
  Access is controlled by the network's access policies.

A tunnel does not authenticate visitors unless the provider explicitly supports
visitor authentication. Cloudflare Access, ngrok traffic policies, Expose
password protection, Pinggy basic auth, and NetBird Expose PIN, password, or
SSO do. Cloudflare Quick Tunnel, Tailscale Funnel, and a bare Pinggy tunnel do
not.

A public ingress tunnel only sees `127.0.0.1:5173` from the host running the
tunnel client. Direct private-overlay traffic reaches the host over a virtual
interface, so a loopback-only service is not reachable. Tailscale Serve is an
exception because it explicitly proxies to `127.0.0.1`. See the private-overlay
sections before changing RAO's bind address.

## Public ingress options

### Option 1, Cloudflare Quick Tunnel

No account. Random `*.trycloudflare.com` subdomain. The URL changes on every run.
Quick Tunnels do not use an API key, API token, tunnel token, or Cloudflare
account. Do not add a Cloudflare secret to `deploy/.env` for this mode.

```sh
cloudflared tunnel --url http://127.0.0.1:5173
```

- Auth. None built in. The URL is public to anyone who has it.
- Limits. 200 concurrent in flight requests, then HTTP 429. No SSE.
- Lifetime. Dies with the process. No SLA or uptime guarantee. Intended for
  testing and development.
- Note. A quick tunnel does not start when a `config.yaml` file exists in the
  `.cloudflared` directory.

### Option 2, Named Cloudflare Tunnel with custom DNS

Requires a Cloudflare account and a domain using Cloudflare nameservers. It
gives a stable hostname and HTTPS. Tunnel connections are outbound only, so no
inbound firewall ports are opened. `cloudflared` maintains encrypted outbound
connections to Cloudflare, and Cloudflare manages the public HTTPS certificate.

Current Cloudflare guidance is to create a dashboard managed tunnel.

1. Go to **Networking** > **Tunnels** and select **Create a tunnel**.
2. Install `cloudflared` on the host and run the shown service command.
3. Add a **Published application** route with hostname `rao-judge.example.com`
   and service URL `http://localhost:5173`.

The dashboard connector command contains a **tunnel token**. This is not the
Cloudflare Global API Key and not a general API token. Treat it as a password for
that one tunnel. Never commit it and never put it in a tracked file.

The helper scripts read the token from `RAO_TUNNEL_TOKEN`, or from a file named
by `RAO_TUNNEL_TOKEN_FILE`. Put the token in the gitignored `deploy/.env` so
`make rao-start` can bring the named tunnel back after a restart. The connector
wrapper passes it to `cloudflared` through the `TUNNEL_TOKEN` environment
variable, so it never appears in a process argument list. See the systemd note
under the recommended path for boot persistence.

A Cloudflare API token is only needed for API or Terraform automation. The
dashboard-managed connector does not need one, and it must never use the account
Global API Key.

A locally managed tunnel is also supported.

```sh
cloudflared tunnel login
cloudflared tunnel create rao-judge
```

`config.yml`

```yaml
tunnel: <UUID>
credentials-file: /home/you/.cloudflared/<UUID>.json
ingress:
  - hostname: rao-judge.example.com
    service: http://127.0.0.1:5173
  - service: http_status:404
```

```sh
cloudflared tunnel route dns <UUID> rao-judge.example.com
cloudflared tunnel run <UUID>
```

Gate it with Cloudflare Access. Create a self hosted public application for the
hostname, add an Allow policy for the judge emails, and pick an identity
provider. Access is deny by default and checks every request for an application
token. Turn on **Protect with Access** on the tunnel so `cloudflared` validates
the token at the origin.

- Auth. Cloudflare Access identity policies, with an email one time PIN or SSO.
- Limits. 1,000 tunnels per account, 25 active replicas per tunnel, 500 Access
  applications.
- Lifetime. Stable. Run `cloudflared` as a system service.
- Domain. Your own name on your Cloudflare zone.
- Note. Without an Access application, a published route is open to anyone on
  the internet.

### Option 3, ngrok

Requires an ngrok account and an authtoken.

```sh
ngrok config add-authtoken <TOKEN>
ngrok http 5173
```

Free plan facts from the official limits page.

- Domain. One assigned `*.ngrok-free.app` dev domain. Custom and reserved
  domains are paid.
- Limits. 1 GB data transfer out per month, 20,000 HTTP requests per month,
  5,000 TCP connections per month, 3 online endpoints, 3 concurrent agents,
  4,000 requests per minute, 1 user, 1 dev domain, 5 traffic policy rules per
  policy. Raw TLS endpoints are not available.
- Auth. The free browser interstitial is not authentication. Add a basic auth
  traffic policy for a real gate.
- Lifetime. Free endpoints have no timeout and can run as a service.

Basic auth policy example from the agent docs.

```yaml
on_http_request:
  - actions:
      - type: basic-auth
        config:
          credentials:
            - judge:password
```

### Option 4, Expose by Beyond Code

Requires an Expose account and token. The client is written in PHP and needs
PHP installed. Install the PHAR and set the token.

```sh
curl https://github.com/exposedev/expose/raw/master/builds/expose -L --output expose
chmod +x expose
./expose token YOUR_TOKEN
./expose share http://127.0.0.1:5173
```

- Auth. Password protection with HTTP basic auth is documented. Whether it is
  available on the free managed plan is not documented.

```sh
./expose share http://127.0.0.1:5173 --basicAuth="judge:secret"
```

- Free plan. TLS/SSL encryption, random URLs, a single EU server, and a time
  limit per connection. No card required.
- Paid plan. Persistent URLs, custom domains, reserved subdomains, access
  control, and the global server network.
- Lifetime. The free connection has a time limit. The exact duration is not
  documented on the pricing page.

### Option 5, Pinggy

No account and no install for the basic path. Uses the stock `ssh` client.

```sh
ssh -p 443 -R0:127.0.0.1:5173 free.pinggy.io
```

Add a visitor password gate.

```sh
ssh -p 443 -R0:127.0.0.1:5173 -t free.pinggy.io b:judge:secret
```

- Auth. Basic auth, key auth, and IP whitelisting are supported for HTTP
  tunnels. These explicitly authenticate visitors.
- Free plan. Random Pinggy URLs, 60 minute tunnel timeout, unlimited data
  transfer. The URL changes on every connect.
- TLS. Pinggy serves an HTTPS URL with a Let's Encrypt certificate.
- Free browser screening. Free tunnels on `*.run.pinggy-free.link` show a one
  time screening page in a browser. It is not authentication. `curl` and non
  browser clients skip it.
- Paid plan. Persistent subdomains and custom domains.
- Lifetime. The 60 minute free timeout is a problem for a timed judging window.

### Option 6, NetBird Expose

Part of the NetBird Reverse Proxy, currently in beta. Requires a NetBird
account, a connected peer, and an admin who enables **Peer Expose** in
**Settings** > **Clients** (NetBird v0.66.0 or later).

```sh
netbird up
netbird expose 5173
```

- Exposure. Public by default. Anyone who knows the generated URL can reach the
  service. Without an auth flag the service has no protection.
- Auth. Optional visitor gates at the edge. The PIN and password are hashed
  with Argon2id. SSO uses your OIDC provider and sessions last 24 hours.

```sh
netbird expose 5173 --with-pin 123456
netbird expose 5173 --with-password judge-secret
netbird expose 5173 --with-user-groups judges
```
- TLS. The proxy terminates TLS at the edge and provisions certificates
  automatically.
- Domain. A generated subdomain on the NetBird proxy cluster by default. Custom
  domains need a pre verified domain in the account.
- Limits. Up to 10 active expose sessions per peer. Session TTL is 90 seconds,
  renewed every 30 seconds. The cloud shared proxy is best effort.
- Private mode. NetBird Only Access keeps the service on the overlay, but
  NetBird Cloud shared clusters do not currently advertise the Private
  capability.
- Loopback. The CLI page calls this a local-port exposure, while the official
  reverse-proxy troubleshooting page says a target bound only to `127.0.0.1` is
  unreachable. Test the generated URL's `/healthz` endpoint first. If it returns
  502, set `WEB_BIND_ADDRESS` to the host's NetBird IP and restart the web
  service. Avoid `0.0.0.0` unless a firewall blocks LAN access.

### Option 7, Tailscale Funnel

Requires a tailnet, MagicDNS, HTTPS certificates, and a funnel node attribute.
Funnel is in beta and available on all plans.

```sh
tailscale funnel 5173
```

- Domain. Only names in your tailnet domain, such as `tailnet-name.ts.net`.
- Auth. Funnel is public. Tailnet policies only control who may create a funnel,
  not who may visit one. There is no per visitor identity.
- Limits. TLS only. Ports 443, 8443 and 10000. Non configurable bandwidth.
- Lifetime. Tied to `tailscaled` and the `tailscale funnel` process.
- Use. Fine when the team already runs Tailscale and an open URL is acceptable.
  Use `tailscale serve` instead to keep it inside the tailnet.

### Option 8, SSH remote forwarding

OpenSSH documents remote forwarding with `-R`. This needs a public host you
control and a domain pointed at it. No tunnel vendor account.

```sh
ssh -N -R 8080:127.0.0.1:5173 user@vps.example.com
```

Remote sockets bind to loopback by default. Public binding needs `GatewayPorts`
on the server. Terminate TLS on the VPS, for example with Caddy proxying to
`127.0.0.1:8080`.

- Auth. SSH keys protect the tunnel. They do not protect the public endpoint.
  Add basic auth, mTLS, or an IP allowlist at the VPS reverse proxy.
- Domain. Any name you control that points at the VPS.
- Lifetime. Dies when `ssh` exits. Use a service manager or a persistent session.

## Private overlay options

### Option 9, Tailscale Serve

Serve shares a local service only with devices in your tailnet. It is private by
design.

```sh
tailscale serve --bg 5173
```

- Exposure. Private to the tailnet. Not on the public internet.
- Client requirement. Every judge must install Tailscale, sign in, and be in the
  tailnet. Access is controlled by tailnet access rules.
- Loopback. Serve supports an HTTP reverse-proxy target on `127.0.0.1`, so RAO
  can keep `WEB_BIND_ADDRESS=127.0.0.1`.
- TLS. HTTPS uses an automatically provisioned certificate.
- Lifetime. With `--bg` it resumes after reboot. Without `--bg` it must be
  restarted manually.
- Note. The same port cannot be both Serve and Funnel at once. The most recent
  command wins.

### Option 10, NetBird private zero-trust network

NetBird builds a WireGuard mesh overlay. It is open source and can run on your
own servers or as NetBird Cloud.

```sh
curl -fsSL https://pkgs.netbird.io/install.sh | sh
netbird up
```

- Exposure. Private to peers in the NetBird network. Not on the public internet.
  Access policies are deny by default.
- Client requirement. Every judge must install the NetBird client and be a peer.
  A user without the client cannot route to the `100.64.0.0/10` overlay address.
- Loopback. This is the main blocker for RAO. NetBird peers cannot reach a
  service bound only to `127.0.0.1`. Traffic arrives on the tunnel interface.
  The app must bind to `0.0.0.0` or the host NetBird IP. Binding `0.0.0.0` also
  exposes the port on the host LAN unless a firewall blocks it.
- Auth. SSO, groups, and posture checks control access. The free plan supports
  Google, Microsoft, and social logins only. OIDC identity providers need the
  Team plan.
- Limits. Free plan up to 5 users and 100 machines.

## Comparison

| Option | Model | Account | Client for judges | Domain | Visitor auth | Stable URL | Free limits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Cloudflare Quick Tunnel | Public | None | None | Random trycloudflare | No | No | 200 in flight, no SSE |
| Cloudflare Named plus Access | Public | Cloudflare plus domain | None | Your DNS | Yes, Access policies | Yes | 1,000 tunnels, 25 replicas |
| ngrok | Public | ngrok | None | Assigned ngrok-free.app | Traffic policy only | Yes | 20k requests, 1 GB per month |
| Expose | Public | Expose | None | Random, custom on Pro | Basic auth, free availability unclear | Paid | Time limit, EU server |
| Pinggy | Public | None | None | Generated, persistent on Pro | Basic auth, key | Paid | 60 minute timeout |
| NetBird Expose | Public | NetBird | None | Generated, custom verified | PIN, password, SSO | While running | 10 sessions per peer |
| Tailscale Funnel | Public | Tailscale | None | tailnet ts.net | No per visitor | Yes | Non configurable bandwidth |
| SSH forwarding | Public | VPS | None | Your VPS DNS | At proxy only | Yes | Your VPS |
| Tailscale Serve | Private | Tailscale | Tailscale | tailnet ts.net | Tailnet rules | Yes | Free plan limits |
| NetBird private | Private | NetBird | NetBird | Overlay IP | Access policies | Yes | 5 users, 100 machines |

## Recommendation matrix for a judge workflow

| Judge workflow | Recommended option | Why |
| --- | --- | --- |
| Zero account instant demo | Cloudflare Quick Tunnel | One command, no signup, no install for judges |
| Stable URL with per judge access | Cloudflare Named Tunnel plus Access | Deny by default identity gate, stable HTTPS |
| Single command with no install | Pinggy | Stock SSH, basic auth gate, no signup |
| Team already on Tailscale, open URL fine | Tailscale Funnel | Fast, judges install nothing, but no visitor gate |
| Private judges only, clients allowed | Tailscale Serve or NetBird private | Overlay only, access policies, no public exposure |
| Existing public VPS | SSH remote forwarding | No vendor account, add auth at the proxy |
| Password gate on a public URL | Pinggy basic auth or NetBird Expose | Provider authenticates visitors at the edge |
| Password gate plus custom domain | ngrok paid or Expose Pro | Free tiers do not offer both |

## Recommended path

Use a named Cloudflare Tunnel with a custom hostname and Cloudflare Access in
front of `127.0.0.1:5173`. It gives a stable HTTPS URL, needs no inbound ports,
and gates judges by email or SSO before they reach the SPA. It is one of the few
options here that adds real per user authentication to an app with no login of
its own.

Run the stack and the supervised connector from the repository. The connector
reads the token from the gitignored `deploy/.env` and restarts itself if the
process exits:

```sh
make rao-start     # stack + named tunnel + sleep inhibitor, all in tmux
make rao-status    # containers, tmux sessions, local and public health
make rao-stop      # stop everything
```

For boot persistence, install `cloudflared` as a service instead. This needs
`sudo`, and the token is stored in the service configuration rather than
`deploy/.env`:

```sh
sudo cloudflared service install <TUNNEL_TOKEN>
```

The `<TUNNEL_TOKEN>` value comes from the connector installation command on the
tunnel's Cloudflare dashboard page. A Quick Tunnel skips this command entirely.

Keep `WEB_BIND_ADDRESS=127.0.0.1`. Change `POSTGRES_PASSWORD` first. Share the
judge hostname only after the tunnel and the Access policy are verified.

Keep the laptop on mains power, disable sleep, and use a stable wired connection
for the judging window. A tunnel cannot keep the application available when the
laptop, Compose stack, or internet connection stops.

Fallback for a zero account demo is a Cloudflare Quick Tunnel. For a no signup
password gate, use Pinggy, but remember the free 60 minute timeout and URL
change. Avoid Tailscale Funnel unless an open URL is acceptable, since it cannot
gate per judge. Do not use a private overlay unless every judge will install the
client. Tailscale Serve handles RAO's loopback binding. Direct NetBird overlay
access requires a NetBird-IP bind, and NetBird Expose needs a `/healthz` check
because its official pages give conflicting loopback guidance.

## Sources

- Cloudflare Quick Tunnels,
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
- Cloudflare Tunnel get started,
  https://developers.cloudflare.com/tunnel/get-started/
- Cloudflare locally managed tunnel,
  https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/
- Cloudflare dashboard managed tunnel,
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/
- Cloudflare Access self hosted public application,
  https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- Cloudflare One account limits,
  https://developers.cloudflare.com/cloudflare-one/account-limits/
- ngrok free plan limits,
  https://ngrok.com/docs/pricing-limits/free-plan-limits/
- ngrok agent,
  https://ngrok.com/docs/agent/
- Expose introduction,
  https://expose.dev/docs/introduction
- Expose installation,
  https://expose.dev/docs/getting-started/installation
- Expose authentication,
  https://expose.dev/docs/getting-started/authentication
- Expose sharing,
  https://expose.dev/docs/client/sharing
- Expose password protection,
  https://expose.dev/docs/client/basic-authentication
- Expose custom domains,
  https://expose.dev/docs/expose-network/custom-domains
- Expose pricing,
  https://expose.dev/#pricing
- Expose source repository,
  https://github.com/exposedev/expose
- Pinggy docs,
  https://pinggy.io/docs/
- Pinggy HTTP tunnels,
  https://pinggy.io/docs/http_tunnels/
- Pinggy basic authentication,
  https://pinggy.io/docs/http_tunnels/basic_auth/
- Pinggy browser screening page,
  https://pinggy.io/docs/http_tunnels/screening/
- Pinggy persistent subdomain,
  https://pinggy.io/docs/persistent_subdomain/
- Pinggy long running tunnels,
  https://pinggy.io/docs/guides/long_running_tunnels/
- Pinggy usage reference,
  https://pinggy.io/docs/usages/
- Pinggy pricing,
  https://pinggy.io/#prices
- NetBird reverse proxy,
  https://docs.netbird.io/manage/reverse-proxy
- NetBird expose from the CLI,
  https://docs.netbird.io/manage/reverse-proxy/expose-from-cli
- NetBird reverse proxy authentication,
  https://docs.netbird.io/manage/reverse-proxy/authentication
- NetBird reverse proxy custom domains,
  https://docs.netbird.io/manage/reverse-proxy/custom-domains
- NetBird reverse proxy troubleshooting,
  https://docs.netbird.io/manage/reverse-proxy/troubleshooting
- NetBird client settings,
  https://docs.netbird.io/manage/settings/clients
- NetBird how it works,
  https://docs.netbird.io/about-netbird/how-netbird-works
- NetBird install on Linux,
  https://docs.netbird.io/get-started/install/linux
- NetBird manage network access,
  https://docs.netbird.io/manage/access-control/manage-network-access
- NetBird single sign on,
  https://docs.netbird.io/manage/team/single-sign-on
- NetBird pricing,
  https://netbird.io/pricing
- Tailscale Funnel,
  https://tailscale.com/kb/1223/funnel
- Tailscale Serve,
  https://tailscale.com/kb/1242/tailscale-serve
- Tailscale pricing,
  https://tailscale.com/pricing
- OpenSSH ssh manual,
  https://man.openbsd.org/ssh.1
