(() => {
  const button = document.querySelector('.comparison-play');
  const videos = Array.from(document.querySelectorAll('.video-pair video'));
  if (!button || videos.length !== 2) return;
  button.hidden = false;
  const sync = () => {
    const playing = videos.some(video => !video.paused && !video.ended);
    button.textContent = playing ? button.dataset.pause : button.dataset.play;
  };
  button.addEventListener('click', async () => {
    if (videos.some(video => !video.paused && !video.ended)) {
      videos.forEach(video => video.pause());
    } else {
      videos.forEach(video => { video.currentTime = 0; });
      const results = await Promise.allSettled(videos.map(video => video.play()));
      if (results.some(result => result.status === 'rejected')) videos.forEach(video => video.pause());
    }
    sync();
  });
  videos.forEach(video => ['play', 'pause', 'ended'].forEach(event => video.addEventListener(event, sync)));
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) videos.forEach(video => video.pause());
  });
})();
