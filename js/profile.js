(() => {
  const links = Array.from(document.querySelectorAll('.section-nav li a'));
  const sections = links.map(link => document.querySelector(link.hash));
  let scheduled = false;

  function updateNavigation() {
    const offset = window.matchMedia('(max-width: 1170px)').matches ? 110 : 90;
    let active = 0;
    sections.forEach((section, index) => {
      if (section.getBoundingClientRect().top <= offset) active = index;
    });
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
      active = sections.length - 1;
    }
    links.forEach((link, index) => {
      if (index === active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
    // Keep the active section visible within the horizontal mobile menu.
    const list = links[active].closest('ul');
    if (list.scrollWidth > list.clientWidth) {
      const item = links[active].getBoundingClientRect();
      const menu = list.getBoundingClientRect();
      if (item.left < menu.left) list.scrollLeft -= menu.left - item.left;
      else if (item.right > menu.right) list.scrollLeft += item.right - menu.right;
    }
    scheduled = false;
  }

  function scheduleUpdate() {
    if (!scheduled) {
      scheduled = true;
      window.requestAnimationFrame(updateNavigation);
    }
  }

  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', scheduleUpdate);
  window.addEventListener('pageshow', scheduleUpdate);
  updateNavigation();
})();
