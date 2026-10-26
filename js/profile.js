(() => {
  const root = document.documentElement;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const compactNav = window.matchMedia('(max-width: 1170px)');

  /* ---------- Theme toggle (persisted, animated with the View Transitions API) ---------- */
  const toggle = document.querySelector('.theme-toggle');
  const systemDark = window.matchMedia('(prefers-color-scheme: dark)');
  const currentTheme = () => root.dataset.theme || (systemDark.matches ? 'dark' : 'light');
  const syncToggle = () => {
    if (toggle) toggle.setAttribute('aria-pressed', String(currentTheme() === 'dark'));
  };
  const applyTheme = theme => {
    root.dataset.theme = theme;
    try { localStorage.setItem('theme', theme); } catch (e) { /* storage unavailable */ }
    syncToggle();
  };
  if (toggle) {
    toggle.addEventListener('click', event => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      if (!document.startViewTransition || reduceMotion.matches) {
        applyTheme(next);
        return;
      }
      const x = event.clientX || toggle.getBoundingClientRect().left + 16;
      const y = event.clientY || toggle.getBoundingClientRect().top + 16;
      const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
      const transition = document.startViewTransition(() => applyTheme(next));
      transition.ready.then(() => {
        root.animate(
          { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
          { duration: 600, easing: 'cubic-bezier(.2,.8,.2,1)', pseudoElement: '::view-transition-new(root)' }
        );
      }).catch(() => {});
    });
  }
  systemDark.addEventListener('change', syncToggle);
  syncToggle();

  /* ---------- Floating topic filter for publications & preprints ---------- */
  const filter = document.querySelector('.topic-filter');
  const researchSections = ['#publications', '#preprints'].map(sel => document.querySelector(sel)).filter(Boolean);
  const papers = researchSections.flatMap(section => Array.from(section.querySelectorAll('.paper[data-topics]')));
  const topicsOf = paper => paper.dataset.topics.split(/\s+/);
  let filterVisible = false;

  function updateFilterVisibility() {
    if (!filter || !researchSections.length) return;
    const first = researchSections[0].getBoundingClientRect();
    const last = researchSections[researchSections.length - 1].getBoundingClientRect();
    const show = first.top < window.innerHeight * 0.55 && last.bottom > window.innerHeight * 0.45;
    if (show !== filterVisible) {
      filterVisible = show;
      filter.classList.toggle('is-visible', show);
    }
  }

  if (filter && papers.length) {
    const chips = Array.from(filter.querySelectorAll('.topic-chip'));
    const emptyNotes = new Map(researchSections.map(section => {
      const note = document.createElement('p');
      note.className = 'topic-empty';
      note.textContent = filter.dataset.empty || '';
      note.hidden = true;
      section.appendChild(note);
      return [section, note];
    }));
    chips.forEach(chip => {
      const topic = chip.dataset.topic;
      const count = chip.querySelector('.topic-count');
      if (count) count.textContent = topic === 'all' ? papers.length : papers.filter(p => topicsOf(p).includes(topic)).length;
    });
    const activeChip = () => chips.find(chip => chip.getAttribute('aria-pressed') === 'true') || chips[0];
    const moveChipIndicator = chip => {
      filter.style.setProperty('--chip-left', `${chip.offsetLeft}px`);
      filter.style.setProperty('--chip-width', `${chip.offsetWidth}px`);
      filter.style.setProperty('--chip-top', `${chip.offsetTop}px`);
      filter.style.setProperty('--chip-height', `${chip.offsetHeight}px`);
      root.style.setProperty('--filter-h', `${filter.offsetHeight}px`);
    };
    const applyTopic = topic => {
      chips.forEach(chip => chip.setAttribute('aria-pressed', String(chip.dataset.topic === topic)));
      moveChipIndicator(activeChip());
      papers.forEach(paper => {
        const match = topic === 'all' || topicsOf(paper).includes(topic);
        if (match && paper.hidden) {
          paper.hidden = false;
          paper.classList.add('is-entering');
          paper.addEventListener('animationend', () => paper.classList.remove('is-entering'), { once: true });
        } else if (!match) {
          paper.hidden = true;
        }
      });
      emptyNotes.forEach((note, section) => {
        note.hidden = Array.from(section.querySelectorAll('.paper[data-topics]')).some(p => !p.hidden);
      });
      scheduleUpdate();
    };
    chips.forEach(chip => chip.addEventListener('click', () => {
      if (chip.getAttribute('aria-pressed') === 'true') return;
      applyTopic(chip.dataset.topic);
      // Start the reader at the top of the filtered list if they were further down.
      if (researchSections[0].getBoundingClientRect().top < 0) {
        researchSections[0].scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth' });
      }
    }));
    filter.hidden = false;
    moveChipIndicator(activeChip());
    window.addEventListener('resize', () => moveChipIndicator(activeChip()));
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => moveChipIndicator(activeChip()));
  }

  /* ---------- Scroll: progress bar, active section, sliding indicator, back-to-top ---------- */
  const links = Array.from(document.querySelectorAll('.section-nav li a'));
  const sections = links.map(link => document.querySelector(link.hash));
  const navList = document.querySelector('.section-nav ul');
  const toTop = document.querySelector('.to-top');
  let scheduled = false;
  let activeIndex = -1;
  const pending = new Set();   // elements still waiting for their scroll reveal
  let observer = null;

  function moveIndicator(link) {
    if (!navList || !link) return;
    navList.style.setProperty('--ind-top', `${link.offsetTop}px`);
    navList.style.setProperty('--ind-height', `${link.offsetHeight}px`);
    navList.style.setProperty('--ind-left', `${link.offsetLeft}px`);
    navList.style.setProperty('--ind-width', `${link.offsetWidth}px`);
  }

  function updateScroll() {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const progress = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
    root.style.setProperty('--scroll', progress.toFixed(4));
    if (toTop) toTop.classList.toggle('is-visible', window.scrollY > 480);

    const offset = compactNav.matches ? 110 : 90;
    let active = 0;
    sections.forEach((section, index) => {
      if (section && section.getBoundingClientRect().top <= offset) active = index;
    });
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
      active = sections.length - 1;
    }
    if (active !== activeIndex) {
      activeIndex = active;
      links.forEach((link, index) => {
        if (index === active) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      });
      // Keep the active section visible within the horizontal compact menu.
      if (navList && navList.scrollWidth > navList.clientWidth) {
        const item = links[active].getBoundingClientRect();
        const menu = navList.getBoundingClientRect();
        if (item.left < menu.left + 12) navList.scrollLeft -= menu.left + 12 - item.left;
        else if (item.right > menu.right - 12) navList.scrollLeft += item.right - (menu.right - 12);
      }
    }
    moveIndicator(links[active]);
    revealPassed();
    updateFilterVisibility();
    scheduled = false;
  }

  function scheduleUpdate() {
    if (!scheduled) {
      scheduled = true;
      window.requestAnimationFrame(updateScroll);
    }
  }

  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', scheduleUpdate);
  window.addEventListener('pageshow', scheduleUpdate);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(scheduleUpdate);
  updateScroll();

  /* ---------- Scroll reveal ---------- */
  // Lists folded inside <details> are excluded: they already animate when the disclosure opens.
  const revealTargets = Array.from(document.querySelectorAll(
    '.profile-copy, .profile-portrait, .page-section h2, .section-note, .paper, .patent, .institution, .news-list, .awards-list, .news-archive, .awards-archive, #beyond p'
  )).filter(el => !el.parentElement.closest('details'));

  function revealElement(el) {
    pending.delete(el);
    if (observer) observer.unobserve(el);
    el.classList.add('is-in');
    // Hand the element back to its own hover transitions once the reveal has played.
    // A timer backs up transitionend, which browsers may skip for off-screen elements.
    const stagger = (Number(el.style.getPropertyValue('--i')) || 0) * 70;
    const cleanup = () => {
      clearTimeout(timer);
      el.classList.remove('reveal', 'is-in');
      el.style.removeProperty('--i');
      el.removeEventListener('transitionend', onEnd);
    };
    const onEnd = e => { if (e.target === el && e.propertyName === 'opacity') cleanup(); };
    const timer = setTimeout(cleanup, stagger + 950);
    el.addEventListener('transitionend', onEnd);
  }

  // Safety net for very fast scrolling: anything already above the viewport is shown immediately.
  function revealPassed() {
    if (!pending.size) return;
    pending.forEach(el => {
      if (el.getBoundingClientRect().bottom < 0) revealElement(el);
    });
  }

  if ('IntersectionObserver' in window && !reduceMotion.matches) {
    observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) revealElement(entry.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });

    const viewportBottom = window.innerHeight;
    revealTargets.forEach(el => {
      const rect = el.getBoundingClientRect();
      // Elements already on screen at load animate in a staggered sequence.
      if (rect.top < viewportBottom) {
        const order = Math.min(8, Math.round(rect.top / 120));
        el.style.setProperty('--i', String(order));
      } else {
        // Stagger siblings that enter together while scrolling.
        const siblings = Array.from(el.parentElement.children).filter(c => c.matches('.paper, .institution, .patent'));
        const index = siblings.indexOf(el);
        if (index > 0) el.style.setProperty('--i', String(Math.min(index, 3)));
      }
      el.classList.add('reveal');
      pending.add(el);
      observer.observe(el);
    });
  }

  /* ---------- Cursor spotlight on paper cards ---------- */
  if (finePointer.matches) {
    document.addEventListener('pointermove', event => {
      const card = event.target.closest && event.target.closest('.paper');
      if (!card) return;
      const rect = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${event.clientX - rect.left}px`);
      card.style.setProperty('--my', `${event.clientY - rect.top}px`);
    }, { passive: true });
  }

  /* ---------- Portrait: align with the bio paragraphs, keep a photo-like ratio ---------- */
  const profile = document.querySelector('.profile');
  const copy = document.querySelector('.profile-copy');
  const wideHero = window.matchMedia('(min-width: 1001px)');
  const PORTRAIT_RATIO = 0.84;   // width / height of the original 250x298 portrait

  function fitPortrait() {
    if (!profile || !copy) return;
    if (!wideHero.matches) {
      ['--portrait-w', '--portrait-top', '--portrait-bottom'].forEach(v => profile.style.removeProperty(v));
      return;
    }
    const paragraphs = copy.querySelectorAll(':scope > p');
    if (!paragraphs.length) return;
    // Widening the photo narrows the text and makes it taller, so settle in a few passes.
    for (let pass = 0; pass < 3; pass++) {
      const copyRect = copy.getBoundingClientRect();
      const first = paragraphs[0].getBoundingClientRect();
      const last = paragraphs[paragraphs.length - 1].getBoundingClientRect();
      const height = last.bottom - first.top;
      const width = Math.round(Math.min(340, Math.max(250, height * PORTRAIT_RATIO)));
      profile.style.setProperty('--portrait-top', `${Math.round(first.top - copyRect.top)}px`);
      profile.style.setProperty('--portrait-bottom', `${Math.round(copyRect.bottom - last.bottom)}px`);
      const previous = profile.style.getPropertyValue('--portrait-w');
      profile.style.setProperty('--portrait-w', `${width}px`);
      if (previous === `${width}px`) break;
    }
  }

  fitPortrait();
  window.addEventListener('resize', () => window.requestAnimationFrame(fitPortrait));
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitPortrait);
  window.addEventListener('load', fitPortrait);

  /* ---------- Portrait tilt ---------- */
  const portrait = document.querySelector('.profile-portrait');
  if (portrait && finePointer.matches && !reduceMotion.matches) {
    const maxTilt = 9;
    portrait.addEventListener('pointermove', event => {
      const rect = portrait.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width - 0.5;
      const py = (event.clientY - rect.top) / rect.height - 0.5;
      portrait.style.setProperty('--tilt-y', `${(px * maxTilt * 2).toFixed(2)}deg`);
      portrait.style.setProperty('--tilt-x', `${(-py * maxTilt * 2).toFixed(2)}deg`);
    });
    portrait.addEventListener('pointerleave', () => {
      portrait.style.setProperty('--tilt-x', '0deg');
      portrait.style.setProperty('--tilt-y', '0deg');
    });
  }

  /* ---------- Figure lightbox ---------- */
  const lightbox = document.querySelector('.lightbox');
  if (lightbox && typeof lightbox.showModal === 'function') {
    const image = lightbox.querySelector('img');
    const caption = lightbox.querySelector('.lightbox-caption');
    const close = () => {
      if (!lightbox.open) return;
      lightbox.close();
    };
    document.addEventListener('click', event => {
      const figure = event.target.closest && event.target.closest('a.paper-figure[href]');
      if (!figure || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
      if (!/\.(webp|png|jpe?g|gif|svg|avif)(\?.*)?$/i.test(figure.getAttribute('href'))) return;
      event.preventDefault();
      const thumb = figure.querySelector('img');
      const paper = figure.closest('.paper');
      const title = paper && paper.querySelector('h3');
      image.src = figure.href;
      image.alt = thumb ? thumb.alt : '';
      caption.textContent = title ? title.textContent.trim() : (thumb ? thumb.alt : '');
      lightbox.showModal();
    });
    lightbox.addEventListener('click', event => {
      // Clicks on the translucent backdrop (outside the image and caption) close the dialog.
      if (event.target === lightbox) close();
    });
    lightbox.querySelector('.lightbox-close').addEventListener('click', close);
    lightbox.addEventListener('close', () => { image.removeAttribute('src'); });
  }
})();
