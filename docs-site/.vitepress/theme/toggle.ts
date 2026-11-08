const TOGGLE_CSS = `
:host { position: absolute; inset: 0; pointer-events: none; }
* { box-sizing: border-box; }
.scene {
  --knob-x: 0px;
  --knob-nudge: 0px;
  position: absolute;
  inset: 0;
  overflow: hidden;
  border-radius: 999px;
  background: #4685c0;
  box-shadow: inset 0 0 4px 2px rgba(9, 9, 11, 0.35);
  transition: background-color 0.7s ease;
}
.scene.is-night { --knob-x: 55px; background: #191e32; }
.scene.is-hovered { --knob-nudge: 2px; }
.knob {
  position: absolute;
  z-index: 4;
  top: 4px;
  left: 4px;
  width: 27px;
  height: 27px;
  border-radius: 50%;
  background: #ffc323;
  box-shadow: 2px 2px 4px rgba(9, 9, 11, 0.35), inset -3px -3px 4px rgba(156, 89, 0, 0.28), inset 3px 3px 4px rgba(255, 255, 210, 0.7);
  transform: translateX(calc(var(--knob-x) + var(--knob-nudge)));
  transition: transform 0.7s cubic-bezier(0.56, 1.35, 0.52, 1), background-color 0.7s ease;
}
.is-night .knob { background: #c3c8d2; }
.crater { position: absolute; border-radius: 50%; background: #96a0b4; box-shadow: inset 1px 1px 2px rgba(9, 9, 11, 0.25); opacity: 0; transition: opacity 0.4s ease; }
.crater:nth-child(1) { width: 6px; height: 6px; top: 5px; left: 8px; }
.crater:nth-child(2) { width: 8px; height: 8px; top: 13px; left: 4px; }
.crater:nth-child(3) { width: 5px; height: 5px; top: 16px; left: 16px; }
.is-night .crater { opacity: 1; }
.stars { position: absolute; inset: 0; opacity: 0; transform: translateY(8px); transition: opacity 0.5s ease, transform 0.8s ease; }
.is-night .stars { opacity: 1; transform: translateY(0); }
.star { position: absolute; width: 3px; height: 3px; border-radius: 50%; background: #fff; animation: star-twinkle 3s ease-in-out infinite alternate; }
.star:nth-child(1) { top: 7px; left: 13px; }
.star:nth-child(2) { top: 23px; left: 24px; animation-delay: -1s; }
.star:nth-child(3) { top: 9px; left: 37px; width: 2px; height: 2px; animation-delay: -2s; }
.star:nth-child(4) { top: 25px; left: 46px; width: 2px; height: 2px; }
.star:nth-child(5) { top: 6px; left: 58px; animation-delay: -1.5s; }
.cloud { position: absolute; z-index: 2; width: 29px; height: 9px; border-radius: 999px; background: rgba(255, 255, 255, 0.9); transition: transform 0.8s ease, opacity 0.6s ease; }
.cloud::before, .cloud::after { content: ""; position: absolute; bottom: 2px; border-radius: 50%; background: inherit; }
.cloud::before { left: 5px; width: 12px; height: 12px; }
.cloud::after { right: 4px; width: 9px; height: 9px; }
.cloud-one { left: 7px; bottom: 5px; }
.cloud-two { right: 5px; bottom: 9px; transform: scale(0.75); opacity: 0.65; }
.is-night .cloud-one { transform: translateY(22px); opacity: 0; }
.is-night .cloud-two { transform: translate(8px, 22px) scale(0.75); opacity: 0; }
.is-hovered .cloud-one { transform: translateX(3px); }
.is-hovered .cloud-two { transform: translate(3px, -1px) scale(0.75); }
.plane, .bear { position: absolute; z-index: 3; pointer-events: none; }
.plane { left: 0; top: 8px; width: 18px; height: 11px; animation: plane-fly 9.5s linear infinite; }
.bear { left: 0; top: 8px; width: 19px; height: 19px; opacity: 0; animation: bear-float 17s linear infinite; }
.is-day .plane { opacity: 0.95; }
.is-night .plane { opacity: 0; }
.is-night .bear { opacity: 0.95; }
@keyframes plane-fly {
  from { transform: translate(-20px, 4px) rotate(-5deg); }
  50% { transform: translate(42px, 0) rotate(3deg); }
  to { transform: translate(98px, 4px) rotate(-4deg); }
}
@keyframes bear-float {
  from { transform: translate(-22px, 6px) rotate(-8deg); }
  50% { transform: translate(43px, 0) rotate(6deg); }
  to { transform: translate(99px, 5px) rotate(-6deg); }
}
@keyframes star-twinkle { from { transform: scale(0.45); opacity: 0.45; } to { transform: scale(1); opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .scene, .knob, .crater, .stars, .cloud { transition: none; }
  .star, .plane, .bear { animation: none; }
  .plane, .bear { display: none; }
}
`

const TOGGLE_HTML = `
<div class="scene is-day">
  <span class="stars" aria-hidden="true"><i class="star"></i><i class="star"></i><i class="star"></i><i class="star"></i><i class="star"></i></span>
  <span class="cloud cloud-one"></span>
  <span class="cloud cloud-two"></span>
  <span class="plane" aria-hidden="true">
    <svg viewBox="0 0 30 18"><path d="M30 9 L1 0.5 L11 9 Z" fill="#fff"/><path d="M30 9 L11 9 L1 17.5 Z" fill="rgba(0,0,0,0.16)"/><path d="M30 9 L6 9" stroke="rgba(0,0,0,0.10)" stroke-width="1" fill="none"/></svg>
  </span>
  <span class="bear" aria-hidden="true">
    <svg viewBox="-20 -20 40 40"><rect x="-9" y="2" width="18" height="14" rx="5" fill="#b9c4d4"/><ellipse cx="0" cy="9" rx="7.5" ry="8" fill="#e6ecf5"/><ellipse cx="-7.6" cy="7" rx="2.8" ry="2.2" fill="#cfd9e6"/><ellipse cx="7.6" cy="7" rx="2.8" ry="2.2" fill="#cfd9e6"/><circle cx="-6.2" cy="-8" r="3.4" fill="#a8845c"/><circle cx="6.2" cy="-8" r="3.4" fill="#a8845c"/><circle cx="-6.2" cy="-8" r="1.7" fill="#c9a583"/><circle cx="6.2" cy="-8" r="1.7" fill="#c9a583"/><circle cx="0" cy="-1.5" r="8" fill="#a8845c"/><ellipse cx="0" cy="2.2" rx="3.6" ry="2.7" fill="#d8b894"/><circle cx="0" cy="1.3" r="1.1" fill="#4a3628"/><circle cx="-3" cy="-3" r="1.15" fill="#2b2b3a"/><circle cx="3" cy="-3" r="1.15" fill="#2b2b3a"/><circle cx="0" cy="-1" r="13.5" fill="rgba(0,0,0,0.16)" stroke="#fff" stroke-width="1.6"/><path d="M-9.5 -8.5 a10.5 10.5 0 0 1 6.5 -7" fill="none" stroke="rgba(255,255,255,0.75)" stroke-width="1.4" stroke-linecap="round"/></svg>
  </span>
  <span class="knob"><i class="crater"></i><i class="crater"></i><i class="crater"></i></span>
</div>
`

type AppearanceWindow = Window & { __advDocsAppearance?: boolean }

export function setupAppearanceToggle() {
  if (typeof window === 'undefined') return
  const global = window as AppearanceWindow
  if (global.__advDocsAppearance) return
  global.__advDocsAppearance = true

  const bindings = new WeakMap<HTMLButtonElement, ShadowRoot>()
  const buttons = () => Array.from(document.querySelectorAll<HTMLButtonElement>('button.VPSwitch'))
  const isDark = () => document.documentElement.classList.contains('dark')
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
  let shiftTimer: number | undefined

  function colorShift() {
    if (reduced()) return
    const root = document.documentElement
    root.classList.add('adv-appearance-shift')
    if (shiftTimer !== undefined) window.clearTimeout(shiftTimer)
    shiftTimer = window.setTimeout(() => root.classList.remove('adv-appearance-shift'), 760)
  }

  function build(button: HTMLButtonElement) {
    const host = document.createElement('div')
    host.className = 'adv-appearance-host'
    host.setAttribute('aria-hidden', 'true')
    const shadow = host.attachShadow({ mode: 'closed' })
    const style = document.createElement('style')
    style.textContent = TOGGLE_CSS
    const container = document.createElement('div')
    container.innerHTML = TOGGLE_HTML
    shadow.append(style, container)
    button.classList.add('adv-appearance-mounted')
    button.appendChild(host)
    return shadow
  }

  function bind(button: HTMLButtonElement) {
    if (bindings.has(button)) return
    const shadow = build(button)
    bindings.set(button, shadow)
    const scene = shadow.querySelector<HTMLElement>('.scene')!
    const sync = () => {
      scene.classList.toggle('is-night', isDark())
      scene.classList.toggle('is-day', !isDark())
    }
    sync()

    let bypass = false
    let busy = false
    button.addEventListener('click', (event) => {
      if (bypass) {
        bypass = false
        return
      }
      if (busy) {
        event.preventDefault()
        event.stopImmediatePropagation()
        return
      }
      colorShift()
      if (event.detail === 0) {
        window.setTimeout(sync, 0)
        return
      }
      event.preventDefault()
      event.stopImmediatePropagation()
      busy = true
      bypass = true
      button.click()
      sync()
      window.setTimeout(() => { busy = false }, 700)
    }, true)
    button.addEventListener('mouseenter', () => {
      if (!reduced()) scene.classList.add('is-hovered')
    })
    button.addEventListener('mouseleave', () => scene.classList.remove('is-hovered'))
  }

  function bindAll() {
    for (const button of buttons()) bind(button)
  }

  bindAll()
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bindAll, { once: true })
  new MutationObserver(bindAll).observe(document.documentElement, { childList: true, subtree: true })
  new MutationObserver(() => {
    for (const button of buttons()) {
      const shadow = bindings.get(button)
      const scene = shadow?.querySelector<HTMLElement>('.scene')
      scene?.classList.toggle('is-night', isDark())
      scene?.classList.toggle('is-day', !isDark())
    }
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
}
