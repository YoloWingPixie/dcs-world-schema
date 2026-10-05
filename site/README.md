# DCS World Reference site

## Deploy

`.github/workflows/site.yml` deploys `main` to Cloudflare Pages. One-time setup:

1. Cloudflare dashboard → Workers & Pages → Create → Pages → Direct Upload: create project `dcs-world-schema` (no upload needed).
2. My Profile → API Tokens → Create token with **Account → Cloudflare Pages → Edit**, scoped to the account.
3. GitHub → Settings → Secrets and variables → Actions:
   - secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` (dashboard → Account home → Account ID);
   - optional variable `CLOUDFLARE_PROJECT_NAME` if the project is not `dcs-world-schema`.
4. Run the workflow (Actions → Site → Run workflow) or push to `main`.
5. Custom domain: project → Custom domains → Set up a domain; the site is built for `/`, no base path.
