/* Shared whos.amung.us map for the English and Chinese homepages. */
(() => {
  'use strict';

  const viewport = document.querySelector('[data-visitor-map]');
  if (!viewport) return;
  const status = viewport.querySelector('.visitor-map-status');

  // Only load tracking on the configured live hostname, excluding local previews.
  if (window.location.hostname !== new URL(viewport.dataset.siteUrl).hostname) {
    status.textContent = viewport.dataset.preview;
    return;
  }

  const canvas = viewport.querySelector('.visitor-map-canvas');
  // Scale the whole map, including its positioned pins, without reloading tracking.
  const resize = () => {
    canvas.style.transform = `scale(${viewport.clientWidth / 420})`;
  };
  resize();
  if ('ResizeObserver' in window) {
    new ResizeObserver(resize).observe(viewport);
  } else {
    window.addEventListener('resize', resize);
  }

  status.textContent = document.documentElement.lang === 'zh-CN' ? '正在加载访客地图…' : 'Loading visitor map…';
  const unavailable = () => { status.textContent = viewport.dataset.unavailable; };
  const timeout = window.setTimeout(unavailable, 15000);

  // The provider inserts the map after this anchor. Keep the fallback until its
  // background actually loads, including when a blocker rejects a later request.
  const observer = new MutationObserver(() => {
    const mapImage = canvas.querySelector('img');
    if (!mapImage) return;
    observer.disconnect();
    const loaded = () => {
      window.clearTimeout(timeout);
      status.hidden = true;
      canvas.classList.add('is-loaded');
      mapImage.alt = document.documentElement.lang === 'zh-CN' ? '世界访客分布地图' : 'World visitor map';
    };
    if (mapImage.complete && mapImage.naturalWidth) loaded();
    else {
      mapImage.addEventListener('load', loaded, { once: true });
      mapImage.addEventListener('error', unavailable, { once: true });
    }
  });
  observer.observe(canvas, { childList: true, subtree: true });

  const anchor = document.createElement('script');
  anchor.id = '_wauvisitors';
  anchor.type = 'application/json';
  canvas.appendChild(anchor);
  window._wau = window._wau || [];
  window._wau.push(['map', viewport.dataset.siteId, 'visitors', '420', '210', 'night', 'star-orange']);

  const script = document.createElement('script');
  script.src = 'https://waust.at/m.js';
  script.async = true;
  script.addEventListener('error', unavailable, { once: true });
  canvas.appendChild(script);
})();
