(() => {
  let library;
  const loadWidgets = () => library ||= new Promise((resolve, reject) => {
    if (window.twttr && window.twttr.widgets) { resolve(window.twttr); return; }
    const script = document.createElement('script');
    script.src = 'https://platform.twitter.com/widgets.js';
    script.async = true;
    script.onload = () => {
      if (!window.twttr) { reject(new Error('X player unavailable')); return; }
      window.twttr.ready(resolve);
    };
    script.onerror = reject;
    document.head.append(script);
  });
  document.querySelectorAll('[data-experience-video]').forEach(container => {
    const host = container.querySelector('.experience-video-embed');
    const fallback = container.querySelector('.experience-video-fallback');
    const load = async () => {
      try {
        const twitter = await loadWidgets();
        const width = Math.round(container.clientWidth);
        // X Publish's Embedded Video mode uses mediaMaxWidth to omit post text.
        const frame = await twitter.widgets.createTweet(container.dataset.tweetId, host, {
          mediaMaxWidth: width, width, dnt: true, conversation: 'none',
          lang: document.documentElement.lang.startsWith('zh') ? 'zh-cn' : 'en'
        });
        if (!frame) return;
        frame.title = document.documentElement.lang.startsWith('zh') ? 'Canva Craft 官方发布视频' : 'Canva Craft official launch video';
        container.classList.add('is-loaded');
        fallback.hidden = true;
      } catch (_) { /* Keep the original poster and direct post link available. */ }
    };
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver(entries => {
        if (!entries[0].isIntersecting) return;
        observer.disconnect();
        load();
      }, { rootMargin: '150px' });
      observer.observe(container);
    } else load();
  });
})();
