(function(){
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const links = document.querySelectorAll('a[href^="/"]');
  links.forEach((a) => {
    a.addEventListener('click', () => {
      const href = a.getAttribute('href');
      if (!href || href === location.pathname || a.target === '_blank') return;
      // Keep normal navigation: no transition overlay / blink effect.
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

  if (!prefersReducedMotion) {
    document.querySelectorAll('.card, .glass.panel').forEach(el => {
      el.addEventListener('mouseenter', () => {
        el.style.transition = 'transform 0.1s ease-out, box-shadow 0.3s ease, background 0.3s ease';
      });
      el.addEventListener('mousemove', e => {
        const rect = el.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        const maxTilt = el.classList.contains('panel') ? 2.5 : 5;
        const tiltX = ((y - centerY) / centerY) * -maxTilt;
        const tiltY = ((x - centerX) / centerX) * maxTilt;
        el.style.transform = `perspective(1000px) scale(1.02) translateY(-4px) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
      });
      el.addEventListener('mouseleave', () => {
        el.style.transition = '';
        el.style.transform = '';
      });
    });
  }

  // Hamburger menu for mobile
  const hamburger = document.getElementById('hamburgerBtn');
  const sidebar = document.getElementById('sidebarEl');
  const overlay = document.getElementById('sidebarOverlay');
  if (hamburger && sidebar) {
    function toggleMenu(open) {
      const isOpen = typeof open === 'boolean' ? open : !sidebar.classList.contains('open');
      sidebar.classList.toggle('open', isOpen);
      if (overlay) overlay.classList.toggle('show', isOpen);
    }
    hamburger.addEventListener('click', () => toggleMenu());
    if (overlay) overlay.addEventListener('click', () => toggleMenu(false));
    // Close sidebar when a nav link is clicked (mobile)
    sidebar.querySelectorAll('nav a').forEach(a => {
      a.addEventListener('click', () => toggleMenu(false));
    });
  }
})();
