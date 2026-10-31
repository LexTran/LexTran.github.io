(() => {
  const hover = matchMedia('(hover: hover) and (pointer: fine)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let activeStop = null;
  document.querySelectorAll('[data-paper-video]').forEach(media => {
    const video = media.querySelector('video');
    const button = media.querySelector('button');
    let requested = false;
    let generation = 0;
    let timer;
    let deadline;
    button.hidden = false;
    video.muted = true;
    const stop = () => {
      requested = false;
      generation++;
      clearTimeout(timer);
      clearTimeout(deadline);
      video.pause();
      if (video.hasAttribute('src')) {
        video.removeAttribute('src');
        video.load(); // Cancel outstanding media downloads and reset the preview.
      }
      media.classList.remove('is-playing');
      button.setAttribute('aria-pressed', 'false');
      button.textContent = button.dataset.play;
      if (activeStop === stop) activeStop = null;
    };
    const start = () => {
      clearTimeout(timer);
      if (requested || button.disabled || document.hidden) return;
      if (activeStop) activeStop();
      activeStop = stop;
      requested = true;
      const attempt = ++generation;
      video.src = media.dataset.videoUrl;
      button.setAttribute('aria-pressed', 'true');
      button.textContent = button.dataset.stop;
      // Keep the original image visible until a frame is actually playing.
      deadline = setTimeout(stop, 15000);
      video.play().then(() => {
        if (!requested || generation !== attempt) return;
        clearTimeout(deadline);
        media.classList.add('is-playing');
      }).catch(() => {
        if (generation === attempt) stop();
      });
    };
    media.addEventListener('pointerenter', event => {
      if (event.pointerType !== 'touch' && hover.matches && !reduced.matches) timer = setTimeout(start, 250);
    });
    // Touch emits pointerleave after each tap; it must not reset the toggle first.
    media.addEventListener('pointerleave', event => { if (event.pointerType !== 'touch') stop(); });
    button.addEventListener('click', () => requested ? stop() : start());
    media.addEventListener('keydown', event => { if (event.key === 'Escape') stop(); });
    media.addEventListener('focusout', event => { if (!media.contains(event.relatedTarget)) stop(); });
    const imageLink = media.querySelector('a.paper-figure');
    if (imageLink) imageLink.addEventListener('click', stop);
    video.addEventListener('error', () => {
      if (!requested) return;
      stop();
      button.disabled = true;
      button.textContent = button.dataset.error;
    });
    // Also stop when a topic filter hides the paper or it leaves the viewport.
    if ('IntersectionObserver' in window) new IntersectionObserver(entries => {
      if (!entries[0].isIntersecting) stop();
    }).observe(media);
    document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
    window.addEventListener('pagehide', stop);
    reduced.addEventListener('change', stop);
  });
})();
