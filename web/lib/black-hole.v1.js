(() => {
  "use strict";

  function createBlackHoleRenderer(canvas, options) {
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) return null;

  const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

  let scene = "home";
  let depth = 0;
  let intensity = 0.55;
  let width = 0;
  let height = 0;
  let pixelRatio = 1;
  let frame = 0;
  let visible = !document.hidden;
  let reducedMotion = reduceMotionQuery.matches;
  let stars = [];
  let diskParticles = [];
  let pointerX = 0;
  let pointerY = 0;
  let pointerTargetX = 0;
  let pointerTargetY = 0;

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function syncSettings() {
    const settings = options.settings();
    scene = ["home", "trap", "blocked"].includes(settings.scene) ? settings.scene : "home";
    depth = Math.max(0, Number.parseInt(settings.depth || "0", 10) || 0);
    intensity = clamp(Number.parseFloat(settings.intensity || "0.55") || 0, 0, 1);
  }

  function hashSeed(value) {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function seededRandom(seedValue) {
    let state = seedValue >>> 0;
    return () => {
      state += 0x6d2b79f5;
      let value = state;
      value = Math.imul(value ^ (value >>> 15), value | 1);
      value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
      return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
    };
  }

  function sceneGeometry() {
    const mobile = width < 720;
    const minimum = Math.min(width, height);
    if (options.embedded) {
      if (scene === "blocked") {
        return { x: width * 0.5, y: height * 0.5, radius: minimum * 0.23 };
      }
      if (scene === "trap") {
        return {
          x: width * (0.56 - intensity * 0.06),
          y: height * 0.46,
          radius: minimum * (0.17 + intensity * 0.09),
        };
      }
      return { x: width * 0.5, y: height * 0.5, radius: minimum * 0.2 };
    }
    if (scene === "blocked") {
      return { x: width * 0.5, y: height * (mobile ? 0.34 : 0.46), radius: minimum * 0.19 };
    }
    if (scene === "trap") {
      const horizontal = mobile ? 0.5 : 0.93 - intensity * 0.24;
      return {
        x: width * horizontal,
        y: height * (mobile ? 0.19 : 0.26),
        radius: minimum * (0.15 + intensity * 0.1),
      };
    }
    return {
      x: width * (mobile ? 0.5 : 0.72),
      y: height * (mobile ? 0.25 : 0.48),
      radius: minimum * (mobile ? 0.105 : 0.145),
    };
  }

  function rebuildParticles() {
    const random = seededRandom(hashSeed(`${scene}:${depth}:${width}x${height}`));
    const area = width * height;
    const starLimit = width < 720 ? 360 : 760;
    const starCount = clamp(Math.floor(area / 2100), 180, starLimit);
    stars = Array.from({ length: starCount }, (_, index) => ({
      x: random(),
      y: random(),
      size: 0.35 + random() * (index % 17 === 0 ? 1.75 : 0.9),
      alpha: 0.18 + random() * 0.76,
      phase: random() * Math.PI * 2,
      temperature: random(),
    }));

    const diskLimit = width < 720 ? 360 : 620;
    const diskCount = Math.floor(diskLimit * (0.62 + intensity * 0.38));
    diskParticles = Array.from({ length: diskCount }, () => {
      const radius = 1.18 + Math.pow(random(), 1.7) * 2.35;
      return {
        radius,
        angle: random() * Math.PI * 2,
        width: 0.7 + random() * 2.2,
        alpha: 0.16 + random() * 0.74,
        heat: clamp(1.35 - radius * 0.25 + random() * 0.35, 0, 1),
        offset: (random() - 0.5) * 0.12,
        speed: 0.11 + 0.38 / Math.pow(radius, 1.5),
      };
    });
  }

  function resize() {
    syncSettings();
    const bounds = canvas.getBoundingClientRect();
    width = Math.max(1, Math.round(bounds.width));
    height = Math.max(1, Math.round(bounds.height));
    pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    rebuildParticles();
    draw(performance.now());
  }

  function drawSpace(time, geometry) {
    const background = context.createRadialGradient(
      geometry.x,
      geometry.y,
      geometry.radius * 0.25,
      geometry.x,
      geometry.y,
      Math.max(width, height) * 0.86,
    );
    background.addColorStop(0, scene === "blocked" ? "#09030d" : "#091024");
    background.addColorStop(0.32, "#050817");
    background.addColorStop(1, "#010207");
    context.fillStyle = background;
    context.fillRect(0, 0, width, height);

    const lensRadius = geometry.radius * (3.1 + intensity * 0.8);
    const parallaxX = pointerX * 9;
    const parallaxY = pointerY * 6;
    for (const star of stars) {
      const sourceX = star.x * width + parallaxX * (0.25 + star.size * 0.2);
      const sourceY = star.y * height + parallaxY * (0.25 + star.size * 0.2);
      const deltaX = sourceX - geometry.x;
      const deltaY = sourceY - geometry.y;
      const distance = Math.max(1, Math.hypot(deltaX, deltaY));
      if (distance < geometry.radius * 0.96) continue;

      const lensFalloff = Math.exp(-Math.pow(distance / lensRadius, 2));
      const displacement = lensFalloff * geometry.radius * (0.12 + intensity * 0.17);
      const x = sourceX + (deltaX / distance) * displacement;
      const y = sourceY + (deltaY / distance) * displacement;
      const twinkle = reducedMotion ? 1 : 0.72 + Math.sin(time * 0.0014 + star.phase) * 0.28;
      const alpha = star.alpha * twinkle * (0.7 + intensity * 0.3);
      const hue = star.temperature > 0.84 ? "164, 218, 255" : star.temperature < 0.12 ? "255, 194, 153" : "224, 234, 255";
      context.strokeStyle = `rgba(${hue},${alpha.toFixed(3)})`;
      context.fillStyle = context.strokeStyle;

      if (lensFalloff > 0.45 && star.size > 0.72) {
        const tangentX = -deltaY / distance;
        const tangentY = deltaX / distance;
        const length = star.size * (1.5 + lensFalloff * 5.5 * intensity);
        context.lineWidth = Math.max(0.45, star.size * 0.58);
        context.beginPath();
        context.moveTo(x - tangentX * length, y - tangentY * length);
        context.lineTo(x + tangentX * length, y + tangentY * length);
        context.stroke();
      } else {
        context.beginPath();
        context.arc(x, y, star.size, 0, Math.PI * 2);
        context.fill();
      }
    }
  }

  function projectedParticle(particle, time, geometry) {
    const speedScale = reducedMotion ? 0 : 0.48 + intensity * 1.18;
    const angle = particle.angle + time * 0.001 * particle.speed * speedScale;
    const radial = particle.radius * geometry.radius;
    const rawX = Math.cos(angle) * radial;
    const rawY = Math.sin(angle) * radial * (0.19 + intensity * 0.035) + particle.offset * geometry.radius;
    const tilt = -0.16;
    return {
      x: geometry.x + rawX * Math.cos(tilt) - rawY * Math.sin(tilt),
      y: geometry.y + rawX * Math.sin(tilt) + rawY * Math.cos(tilt),
      front: Math.sin(angle) > 0,
      angle,
    };
  }

  function drawDiskBand(geometry) {
    context.save();
    context.translate(geometry.x, geometry.y);
    context.rotate(-0.16);
    context.scale(1, 0.21 + intensity * 0.03);
    context.globalCompositeOperation = "lighter";
    const diskGlow = context.createRadialGradient(0, 0, geometry.radius * 1.05, 0, 0, geometry.radius * 3.5);
    diskGlow.addColorStop(0, "rgba(255,255,235,0)");
    diskGlow.addColorStop(0.38, `rgba(255,178,82,${0.08 + intensity * 0.08})`);
    diskGlow.addColorStop(0.61, `rgba(255,79,35,${0.055 + intensity * 0.055})`);
    diskGlow.addColorStop(1, "rgba(67,35,129,0)");
    context.fillStyle = diskGlow;
    context.beginPath();
    context.arc(0, 0, geometry.radius * 3.55, 0, Math.PI * 2);
    context.fill();
    context.shadowBlur = geometry.radius * 0.22;
    context.shadowColor = `rgba(255,112,52,${0.24 + intensity * 0.24})`;
    for (let ring = 0; ring < 5; ring += 1) {
      context.strokeStyle = `rgba(255,${112 + ring * 22},${55 + ring * 19},${0.055 + intensity * 0.035})`;
      context.lineWidth = geometry.radius * (0.14 - ring * 0.018);
      context.beginPath();
      context.arc(0, 0, geometry.radius * (1.42 + ring * 0.39), 0, Math.PI * 2);
      context.stroke();
    }
    context.restore();
  }

  function drawDiskParticles(time, geometry, front) {
    context.save();
    context.globalCompositeOperation = "lighter";
    for (const particle of diskParticles) {
      const point = projectedParticle(particle, time, geometry);
      if (point.front !== front) continue;
      const proximity = clamp((3.65 - particle.radius) / 2.6, 0, 1);
      const alpha = particle.alpha * (0.35 + intensity * 0.65) * (0.55 + proximity * 0.45);
      const red = 255;
      const green = Math.round(70 + particle.heat * 174);
      const blue = Math.round(38 + particle.heat * 176);
      context.fillStyle = `rgba(${red},${green},${blue},${alpha.toFixed(3)})`;
      const stretch = particle.width * (1 + proximity * intensity * 2.1);
      context.save();
      context.translate(point.x, point.y);
      context.rotate(point.angle + Math.PI / 2 - 0.16);
      context.beginPath();
      context.ellipse(0, 0, stretch, Math.max(0.4, particle.width * 0.42), 0, 0, Math.PI * 2);
      context.fill();
      context.restore();
    }
    context.restore();
  }

  function drawEventHorizon(geometry) {
    const radius = geometry.radius;
    const halo = context.createRadialGradient(
      geometry.x,
      geometry.y,
      radius * 0.65,
      geometry.x,
      geometry.y,
      radius * 1.65,
    );
    halo.addColorStop(0, "rgba(255,102,45,0)");
    halo.addColorStop(0.28, `rgba(255,112,52,${0.1 + intensity * 0.08})`);
    halo.addColorStop(0.42, `rgba(255,211,161,${0.28 + intensity * 0.18})`);
    halo.addColorStop(0.53, `rgba(255,126,58,${0.12 + intensity * 0.1})`);
    halo.addColorStop(1, "rgba(255,91,42,0)");
    context.save();
    context.globalCompositeOperation = "lighter";
    context.fillStyle = halo;
    context.beginPath();
    context.arc(geometry.x, geometry.y, radius * 1.65, 0, Math.PI * 2);
    context.fill();
    context.restore();

    context.save();
    context.globalCompositeOperation = "lighter";
    context.shadowBlur = 34 + intensity * 42;
    context.shadowColor = `rgba(255,154,72,${0.56 + intensity * 0.32})`;
    context.strokeStyle = `rgba(255,226,184,${0.68 + intensity * 0.28})`;
    context.lineWidth = Math.max(2, radius * (0.024 + intensity * 0.012));
    context.beginPath();
    context.arc(geometry.x, geometry.y, radius * 1.075, 0, Math.PI * 2);
    context.stroke();
    context.restore();

    const horizon = context.createRadialGradient(
      geometry.x - radius * 0.15,
      geometry.y - radius * 0.18,
      radius * 0.08,
      geometry.x,
      geometry.y,
      radius * 1.08,
    );
    horizon.addColorStop(0, "#000000");
    horizon.addColorStop(0.78, "#000000");
    horizon.addColorStop(0.95, "rgba(0,0,0,0.98)");
    horizon.addColorStop(1, "rgba(0,0,0,0)");
    context.fillStyle = horizon;
    context.beginPath();
    context.arc(geometry.x, geometry.y, radius * 1.1, 0, Math.PI * 2);
    context.fill();

    context.save();
    context.globalCompositeOperation = "screen";
    context.strokeStyle = `rgba(131,211,255,${0.08 + intensity * 0.13})`;
    context.lineWidth = Math.max(1, radius * 0.012);
    context.beginPath();
    context.arc(geometry.x, geometry.y, radius * 1.22, Math.PI * 1.04, Math.PI * 1.92);
    context.stroke();
    context.restore();
  }

  function drawVignette(geometry) {
    const radius = Math.max(width, height) * 0.74;
    const vignette = context.createRadialGradient(geometry.x, geometry.y, geometry.radius, geometry.x, geometry.y, radius);
    vignette.addColorStop(0, "rgba(0,0,0,0)");
    vignette.addColorStop(0.58, `rgba(0,0,6,${0.08 + intensity * 0.1})`);
    vignette.addColorStop(1, `rgba(0,0,5,${0.68 + intensity * 0.18})`);
    context.fillStyle = vignette;
    context.fillRect(0, 0, width, height);
  }

  function draw(time) {
    if (!width || !height) return;
    pointerX += (pointerTargetX - pointerX) * 0.035;
    pointerY += (pointerTargetY - pointerY) * 0.035;
    const base = sceneGeometry();
    const geometry = {
      x: base.x + pointerX * (scene === "home" ? 12 : 5),
      y: base.y + pointerY * (scene === "home" ? 8 : 3),
      radius: base.radius * (1 + (reducedMotion ? 0 : Math.sin(time * 0.0007) * 0.012 * intensity)),
    };
    drawSpace(time, geometry);
    drawDiskBand(geometry);
    drawDiskParticles(time, geometry, false);
    drawEventHorizon(geometry);
    drawDiskParticles(time, geometry, true);
    drawVignette(geometry);
    options.onReady();
  }

  function animate(time) {
    draw(time);
    if (visible && !reducedMotion) frame = window.requestAnimationFrame(animate);
  }

  function restart() {
    window.cancelAnimationFrame(frame);
    draw(performance.now());
    if (visible && !reducedMotion) frame = window.requestAnimationFrame(animate);
  }

  const pointerSurface = options.pointerSurface || window;
  function handlePointerMove(event) {
    const bounds = canvas.getBoundingClientRect();
    pointerTargetX = clamp((event.clientX - bounds.left) / Math.max(1, bounds.width) - 0.5, -0.5, 0.5);
    pointerTargetY = clamp((event.clientY - bounds.top) / Math.max(1, bounds.height) - 0.5, -0.5, 0.5);
  }
  function handlePointerLeave() {
    pointerTargetX = 0;
    pointerTargetY = 0;
  }
  function handleVisibilityChange() {
    visible = !document.hidden;
    restart();
  }
  function handleMotionChange(event) {
    reducedMotion = event.matches;
    restart();
  }

  pointerSurface.addEventListener("pointermove", handlePointerMove, { passive: true });
  pointerSurface.addEventListener("pointerleave", handlePointerLeave, { passive: true });
  window.addEventListener("resize", resize, { passive: true });
  document.addEventListener("visibilitychange", handleVisibilityChange);
  reduceMotionQuery.addEventListener?.("change", handleMotionChange);
  const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
  resizeObserver?.observe(canvas);

  resize();
  restart();

  return {
    update() {
      syncSettings();
      rebuildParticles();
      restart();
    },
    destroy() {
      window.cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      pointerSurface.removeEventListener("pointermove", handlePointerMove);
      pointerSurface.removeEventListener("pointerleave", handlePointerLeave);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      reduceMotionQuery.removeEventListener?.("change", handleMotionChange);
    },
  };
  }

  function intensityFromDepth(depth) {
    return Math.min(1, 0.2 + Math.max(0, depth) * 0.2);
  }

  class EventHorizonVisual extends HTMLElement {
    static get observedAttributes() {
      return ["scene", "depth", "intensity"];
    }

    constructor() {
      super();
      const shadow = this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = ":host{display:block;position:relative;overflow:hidden;min-height:240px;aspect-ratio:16/9;background:#02030a;contain:layout paint style}:host([hidden]){display:none}canvas{position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none}";
      this.canvas = document.createElement("canvas");
      this.canvas.setAttribute("aria-hidden", "true");
      shadow.append(style, this.canvas);
      this.renderer = null;
    }

    settings() {
      const depth = Math.max(0, Number.parseInt(this.getAttribute("depth") || "0", 10) || 0);
      const explicitIntensity = this.getAttribute("intensity");
      return {
        scene: this.getAttribute("scene") || "home",
        depth,
        intensity: explicitIntensity == null ? intensityFromDepth(depth) : explicitIntensity,
      };
    }

    connectedCallback() {
      if (this.renderer) return;
      if (this.hasAttribute("aria-label") && !this.hasAttribute("role")) this.setAttribute("role", "img");
      this.renderer = createBlackHoleRenderer(this.canvas, {
        embedded: true,
        pointerSurface: this,
        settings: () => this.settings(),
        onReady: () => { this.dataset.blackHoleReady = "true"; },
      });
    }

    disconnectedCallback() {
      this.renderer?.destroy();
      this.renderer = null;
      delete this.dataset.blackHoleReady;
    }

    attributeChangedCallback() {
      this.renderer?.update();
    }
  }

  if (window.customElements && !window.customElements.get("event-horizon-visual")) {
    window.customElements.define("event-horizon-visual", EventHorizonVisual);
  }

  const pageCanvas = document.querySelector("[data-black-hole-canvas]");
  if (pageCanvas instanceof HTMLCanvasElement && pageCanvas.dataset.blackHoleMounted !== "true") {
    pageCanvas.dataset.blackHoleMounted = "true";
    createBlackHoleRenderer(pageCanvas, {
      embedded: false,
      pointerSurface: window,
      settings: () => ({
        scene: document.body.dataset.blackHoleScene || "home",
        depth: document.body.dataset.depth || "0",
        intensity: document.body.dataset.intensity || "0.55",
      }),
      onReady: () => { document.documentElement.dataset.blackHoleReady = "true"; },
    });
  }
})();
