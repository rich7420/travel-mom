'use strict';

const fontButtons = [...document.querySelectorAll('[data-guide-font]')];
function setGuideFont(scale) {
  if (!['normal', 'large', 'xlarge'].includes(scale)) scale = 'large';
  document.documentElement.dataset.font = scale;
  fontButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.guideFont === scale)));
  try { localStorage.setItem('momGuideFont', scale); } catch { /* Reading help works with storage disabled. */ }
}
let savedFont = 'large';
try { savedFont = localStorage.getItem('momGuideFont') || 'large'; } catch { /* Use readable defaults. */ }
setGuideFont(savedFont);
fontButtons.forEach(button => button.addEventListener('click', () => setGuideFont(button.dataset.guideFont)));
document.getElementById('printGuide').addEventListener('click', () => window.print());
document.getElementById('guideTools').classList.remove('hidden');

const compactContents = window.matchMedia('(max-width: 900px)');
const contents = document.getElementById('guideContents');
function adaptContents() { contents.open = !compactContents.matches; }
adaptContents();
compactContents.addEventListener('change', adaptContents);
