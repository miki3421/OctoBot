/* Local navigation only: links, responsive drawer and keyboard access. */
(()=>{'use strict';
const sidebar=document.getElementById('lab-sidebar'),toggle=document.getElementById('lab-menu-toggle'),close=document.getElementById('lab-menu-close'),backdrop=document.getElementById('lab-nav-backdrop'),main=document.getElementById('lab-main-content');
if(!sidebar||!toggle||!main)return;
const mobile=window.matchMedia('(max-width:1099px)'),path=location.pathname.replace(/\/+$/,'')||'/';
let active=null;
for(const link of sidebar.querySelectorAll('[data-lab-route]')){
 const routes=[link.getAttribute('href'),...(link.dataset.labAliases||'').split(' ').filter(Boolean)];
 if(routes.includes(path)){link.setAttribute('aria-current','page');active=link;}else link.removeAttribute('aria-current');
}
document.getElementById('lab-current-page').textContent=active?active.textContent:'Trading AI Lab';
function open(){if(!mobile.matches)return;document.body.classList.add('lab-menu-open');sidebar.inert=false;sidebar.removeAttribute('aria-hidden');sidebar.setAttribute('role','dialog');sidebar.setAttribute('aria-modal','true');toggle.setAttribute('aria-expanded','true');main.inert=true;close.focus();}
function shut(restore=true){const wasOpen=document.body.classList.contains('lab-menu-open');document.body.classList.remove('lab-menu-open');toggle.setAttribute('aria-expanded','false');sidebar.removeAttribute('role');sidebar.removeAttribute('aria-modal');main.inert=false;sidebar.inert=mobile.matches;if(mobile.matches)sidebar.setAttribute('aria-hidden','true');else sidebar.removeAttribute('aria-hidden');if(restore&&wasOpen&&mobile.matches)toggle.focus();}
toggle.addEventListener('click',()=>document.body.classList.contains('lab-menu-open')?shut():open());close.addEventListener('click',()=>shut());backdrop.addEventListener('click',()=>shut());
sidebar.addEventListener('click',event=>{if(event.target.closest('a[href]')&&mobile.matches)shut(false);});
document.addEventListener('keydown',event=>{
 if(!document.body.classList.contains('lab-menu-open'))return;
 if(event.key==='Escape'){event.preventDefault();shut();return;}
 if(event.key==='Tab'){
  const items=[...sidebar.querySelectorAll('a[href],button:not([disabled])')].filter(n=>n.getClientRects().length),first=items[0],last=items.at(-1);
  if(event.shiftKey&&(document.activeElement===first||!sidebar.contains(document.activeElement))){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&(document.activeElement===last||!sidebar.contains(document.activeElement))){event.preventDefault();first.focus();}
 }
});
mobile.addEventListener('change',()=>shut(false));shut(false);
})();
