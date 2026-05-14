(function(){
  const links = document.querySelectorAll('a[href^="/"]');
  links.forEach((a) => {
    a.addEventListener('click', (e) => {
      const href = a.getAttribute('href');
      if (!href || href === location.pathname || a.target === '_blank') return;
      e.preventDefault();
      document.body.classList.add('page-leave');
      setTimeout(() => { window.location.href = href; }, 180);
    });
  });

  const content = document.querySelector('.content');
  if (content) {
    Array.from(content.children).forEach((el, idx) => {
      el.classList.add('reveal');
      el.style.animationDelay = `${Math.min(idx * 55, 260)}ms`;
    });
  }
})();
