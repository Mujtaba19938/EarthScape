// Website behaviour: menu, FAQ, tabs, slider, hero videos and messages.
// The pages work without it; this only adds the moving parts.

// Mobile menu
for (const nav of document.querySelectorAll('.ui-nav')) {
  const menu = nav.querySelector('.ui-nav-menu');
  for (const button of nav.querySelectorAll('.ui-nav-button')) {
    button.setAttribute('role', 'button');
    button.setAttribute('tabindex', '0');
    button.setAttribute('aria-label', 'Menu');
    const toggle = () => {
      const open = !button.classList.contains('is-open');
      for (const each of nav.querySelectorAll('.ui-nav-button')) each.classList.toggle('is-open', open);
      if (open) menu.setAttribute('data-nav-menu-open', '');
      else menu.removeAttribute('data-nav-menu-open');
      button.setAttribute('aria-expanded', String(open));
    };
    button.addEventListener('click', toggle);
    button.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); }
    });
  }
}

// FAQ answers
for (const item of document.querySelectorAll('.ui-dropdown')) {
  const toggle = item.querySelector('.ui-dropdown-toggle');
  const answer = item.querySelector('.ui-dropdown-list');
  if (!toggle || !answer) continue;
  toggle.setAttribute('role', 'button');
  toggle.setAttribute('tabindex', '0');
  toggle.setAttribute('aria-expanded', 'false');
  const setOpen = (open) => {
    toggle.classList.toggle('is-open', open);
    answer.classList.toggle('is-open', open);
    item.classList.toggle('is-open', open);
    answer.style.height = open ? answer.scrollHeight + 'px' : '0px';
    toggle.setAttribute('aria-expanded', String(open));
  };
  toggle.addEventListener('click', () => setOpen(!answer.classList.contains('is-open')));
  toggle.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle.click(); }
  });
}

// Tabs
for (const tabs of document.querySelectorAll('.ui-tabs')) {
  const links = tabs.querySelectorAll('.ui-tab-link');
  const panes = tabs.querySelectorAll('.ui-tab-pane');
  for (const link of links) {
    link.setAttribute('role', 'tab');
    link.setAttribute('href', '#');
    link.addEventListener('click', (event) => {
      event.preventDefault();
      for (const each of links) {
        each.classList.toggle('is-current', each === link);
        each.setAttribute('aria-selected', String(each === link));
      }
      for (const pane of panes) pane.classList.toggle('is-active', pane.dataset.tab === link.dataset.tab);
    });
  }
}

// Testimonial slider
for (const slider of document.querySelectorAll('.ui-slider')) {
  const slides = [...slider.querySelectorAll('.ui-slide')];
  if (slides.length < 2) continue;
  let index = 0;
  const show = (next) => {
    index = (next + slides.length) % slides.length;
    for (const slide of slides) {
      slide.style.transition = 'transform ' + (slider.dataset.duration || 500) + 'ms ease';
      slide.style.transform = 'translateX(' + (-100 * index) + '%)';
    }
  };
  slider.querySelector('.ui-slider-arrow-left')?.addEventListener('click', () => { show(index - 1); restart(); });
  slider.querySelector('.ui-slider-arrow-right')?.addEventListener('click', () => { show(index + 1); restart(); });
  // Autoplay
  let timer = null;
  const restart = () => {
    clearInterval(timer);
    timer = setInterval(() => show(index + 1), Number(slider.dataset.delay) || 4000);
  };
  restart();
}

// Hero videos
const hero = document.querySelector('.section_home-hero');
if (hero) {
  const order = ['is_first', 'is_second', 'is_third'];
  const videos = order.map((name) => hero.querySelector('.background-video-hero.' + name + ', .background-video-hero.' + name.replace('_', '-')));
  const thumbs = order.map((name) => hero.querySelector('.video-item.' + name));
  const bars = order.map((name) => hero.querySelector('.fill_progress.' + name));
  const seconds = 8;
  let current = 0;
  let timer = null;
  const play = (next) => {
    current = next % order.length;
    videos.forEach((video, i) => {
      if (!video) return;
      video.style.transition = 'opacity 1s ease';
      video.style.opacity = i === current ? '1' : '0';
    });
    thumbs.forEach((thumb, i) => thumb && (thumb.style.borderColor = i === current ? '#fff' : 'transparent'));
    bars.forEach((bar, i) => {
      if (!bar) return;
      bar.style.transition = 'none';
      bar.style.width = i < current ? '100%' : '0%';
      if (i === current) {
        void bar.offsetWidth;
        bar.style.transition = 'width ' + seconds + 's linear';
        bar.style.width = '100%';
      }
    });
    clearTimeout(timer);
    timer = setTimeout(() => play(current + 1), seconds * 1000);
  };
  thumbs.forEach((thumb, i) => thumb && thumb.addEventListener('click', () => play(i)));
  play(0);
}

// Video play and pause
for (const button of document.querySelectorAll('.ui-background-video--control')) {
  const video = document.getElementById(button.getAttribute('aria-controls'));
  if (!video) continue;
  const [pauseIcon, playIcon] = button.querySelectorAll(':scope > span');
  const update = () => {
    if (pauseIcon) pauseIcon.hidden = video.paused;
    if (playIcon) playIcon.hidden = !video.paused;
  };
  button.addEventListener('click', () => { if (video.paused) video.play(); else video.pause(); });
  video.addEventListener('play', update);
  video.addEventListener('pause', update);
}

// Map tooltips on scroll
if ('IntersectionObserver' in window) {
  const watcher = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) { entry.target.classList.add('is-visible'); watcher.unobserve(entry.target); }
    }
  }, { threshold: 0.3 });
  for (const map of document.querySelectorAll('.world-tooltip')) watcher.observe(map);
} else {
  for (const map of document.querySelectorAll('.world-tooltip')) map.classList.add('is-visible');
}

// Hide messages
for (const message of document.querySelectorAll('[data-message]')) {
  setTimeout(() => message.remove(), 6000);
}
