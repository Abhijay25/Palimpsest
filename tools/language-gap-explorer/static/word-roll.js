(() => {
  'use strict';
  const roll = document.getElementById('issue-word-roll');
  if (!roll) return;
  const words = [...roll.children], screen = document.getElementById('entry-screen');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let index = 0, timer, hovering = false;
  function schedule() {
    clearTimeout(timer);
    if (hovering || reduced.matches || document.hidden || screen.hidden || screen.contains(document.activeElement)) return;
    timer = setTimeout(() => {
      words.forEach(word => word.classList.remove('is-previous'));
      words[index].classList.replace('is-current', 'is-previous');
      index = (index + 1) % words.length;
      words[index].classList.add('is-current');
      schedule();
    }, 2800);
  }
  roll.addEventListener('pointerenter', () => { hovering = true; schedule(); });
  roll.addEventListener('pointerleave', () => { hovering = false; schedule(); });
  screen.addEventListener('focusin', schedule);
  screen.addEventListener('focusout', () => queueMicrotask(schedule));
  document.addEventListener('visibilitychange', schedule);
  reduced.addEventListener('change', schedule);
  new MutationObserver(schedule).observe(screen, { attributes: true, attributeFilter: ['hidden'] });
  addEventListener('pagehide', () => clearTimeout(timer));
  addEventListener('pageshow', schedule);
  schedule();
})();
