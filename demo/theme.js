(() => {
  const themes = new Set(['summer-beach', 'ocean-breeze', 'brand-visuals']);
  const requestedTheme = new URLSearchParams(window.location.search).get('theme');
  const theme = themes.has(requestedTheme) ? requestedTheme : 'summer-beach';

  document.documentElement.dataset.theme = theme;

  window.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('a[href]').forEach((link) => {
      const href = link.getAttribute('href');
      if (!href || href.startsWith('#')) return;

      const url = new URL(href, window.location.href);
      if (url.origin !== window.location.origin || !url.pathname.endsWith('.html')) return;

      url.searchParams.set('theme', theme);
      link.href = `${url.pathname.split('/').pop()}${url.search}${url.hash}`;
    });
  });
})();