const links = [['/', '论文探索'], ['/review.html', '单篇审稿'], ['/reviewers.html', '领域 Skill 库']];
const nav = document.createElement('nav'); nav.className = 'site-nav'; nav.setAttribute('aria-label', '主题页面');
for (const [href, text] of links) {
  const a = document.createElement('a'); a.href = href; a.textContent = text;
  if (location.pathname === href || href === '/' && location.pathname === '/index.html') a.setAttribute('aria-current', 'page');
  nav.append(a);
}
const style = document.createElement('style');
style.textContent = `.site-nav{display:flex;gap:8px;flex-wrap:wrap;margin:0;padding:12px max(20px,calc((100% - 1552px)/2));background:#fff;border-bottom:1px solid #dce3ed;line-height:1.5}.site-nav a{color:#435875;text-decoration:none;padding:8px 16px;border-radius:6px;font:600 14px/1.5 system-ui,sans-serif}.site-nav a:hover{background:#f0f5fa}.site-nav a[aria-current=page]{background:#e8f0fc;color:#164b93}.site-nav a:focus-visible{outline:3px solid #2563eb;outline-offset:2px}`;
document.head.append(style); document.body.prepend(nav);
