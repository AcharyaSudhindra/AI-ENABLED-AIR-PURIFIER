(function(){
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const sceneTransition = document.getElementById('sceneTransition');
  if (!prefersReducedMotion && sceneTransition) {
    document.body.classList.add('scene-enter');
    setTimeout(() => document.body.classList.remove('scene-enter'), 420);
  }
  const links = document.querySelectorAll('a[href^="/"]');
  links.forEach((a) => {
    a.addEventListener('click', (e) => {
      const href = a.getAttribute('href');
      if (!href || href === location.pathname || a.target === '_blank') return;
      e.preventDefault();
      document.body.classList.add('page-leave');
      if (!prefersReducedMotion && sceneTransition) document.body.classList.add('scene-leave');
      setTimeout(() => { window.location.href = href; }, prefersReducedMotion ? 180 : 420);
    });
  });

  const content = document.querySelector('.content');
  if (content) {
    Array.from(content.children).forEach((el, idx) => {
      el.classList.add('reveal');
      el.style.animationDelay = `${Math.min(idx * 55, 260)}ms`;
    });
  }

  const path = window.location.pathname;
  document.querySelectorAll('.sidebar nav a[href^="/"]').forEach((a) => {
    if (a.getAttribute('href') === path) a.classList.add('active');
  });

  if (!prefersReducedMotion && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.18 });
    document.querySelectorAll('.panel canvas, table, .alerts li').forEach((el) => {
      el.classList.add('scroll-reveal');
      io.observe(el);
    });
  }

  if (!prefersReducedMotion) {
    const numEls = document.querySelectorAll('.card p, .ring span');
    numEls.forEach((el) => {
      const txt = (el.textContent || '').trim();
      const n = Number(txt.replace(/[^\d.-]/g, ''));
      if (!Number.isFinite(n)) return;
      const hasDecimal = /\./.test(txt);
      const suffix = txt.replace(/^[\d.\-]+/, '');
      const dur = 520;
      const start = performance.now();
      const from = 0;
      function frame(t){
        const p = Math.min(1, (t - start) / dur);
        const eased = 1 - Math.pow(1 - p, 3);
        const val = from + (n - from) * eased;
        el.textContent = `${hasDecimal ? val.toFixed(1) : val.toFixed(0)}${suffix}`;
        if (p < 1) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });
  }

  if (!prefersReducedMotion && window.innerWidth > 1024) {
    const depthEls = document.querySelectorAll('.card, .panel');
    const damp = 8;
    depthEls.forEach((el) => {
      el.addEventListener('mousemove', (e) => {
        const r = el.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - 0.5;
        const y = (e.clientY - r.top) / r.height - 0.5;
        const rx = (-y * damp).toFixed(2);
        const ry = (x * damp).toFixed(2);
        el.style.transform = `perspective(1000px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(-2px)`;
      });
      el.addEventListener('mouseleave', () => {
        el.style.transform = '';
      });
    });

    const bgfx = document.querySelector('.bgfx');
    const orbs = Array.from(document.querySelectorAll('.bg-orb'));
    window.addEventListener('mousemove', (e) => {
      const x = (e.clientX / window.innerWidth - 0.5) * 2;
      const y = (e.clientY / window.innerHeight - 0.5) * 2;
      if (bgfx) bgfx.style.transform = `translate3d(${(-x * 6).toFixed(2)}px, ${(-y * 6).toFixed(2)}px, 0)`;
      orbs.forEach((orb, i) => {
        const m = (i + 1) * 10;
        orb.style.transform = `translate3d(${(x * m).toFixed(2)}px, ${(y * m).toFixed(2)}px, 0)`;
      });
    }, { passive: true });
  }
})();
