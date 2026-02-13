/** Particle system engine for rain, snow, and dust motes. */

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  opacity: number;
  size: number;
}

export interface ParticleSystem {
  particles: Particle[];
  type: 'rain' | 'snow' | 'dust';
}

function createRainParticles(width: number, height: number): Particle[] {
  return Array.from({ length: 200 }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    vx: -0.5 + Math.random() * 0.3,
    vy: 8 + Math.random() * 4,
    opacity: 0.15 + Math.random() * 0.25,
    size: 1 + Math.random() * 1.5,
  }));
}

function createSnowParticles(width: number, height: number): Particle[] {
  return Array.from({ length: 80 }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    vx: -0.3 + Math.random() * 0.6,
    vy: 0.5 + Math.random() * 1.5,
    opacity: 0.4 + Math.random() * 0.4,
    size: 2 + Math.random() * 3,
  }));
}

function createDustParticles(width: number, height: number): Particle[] {
  return Array.from({ length: 15 }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    vx: -0.2 + Math.random() * 0.4,
    vy: -0.1 + Math.random() * 0.2,
    opacity: 0.05 + Math.random() * 0.1,
    size: 1.5 + Math.random() * 2,
  }));
}

export function createParticleSystem(
  type: 'rain' | 'snow' | 'dust',
  width: number,
  height: number,
): ParticleSystem {
  let particles: Particle[];
  switch (type) {
    case 'rain':
      particles = createRainParticles(width, height);
      break;
    case 'snow':
      particles = createSnowParticles(width, height);
      break;
    case 'dust':
      particles = createDustParticles(width, height);
      break;
  }
  return { particles, type };
}

export function updateParticles(
  system: ParticleSystem,
  width: number,
  height: number,
): void {
  for (const p of system.particles) {
    p.x += p.vx;
    p.y += p.vy;

    // Wrap around
    if (p.y > height) {
      p.y = -p.size;
      p.x = Math.random() * width;
    }
    if (p.y < -p.size * 2) {
      p.y = height + p.size;
    }
    if (p.x < -p.size) {
      p.x = width + p.size;
    }
    if (p.x > width + p.size) {
      p.x = -p.size;
    }

    // Dust: gentle random walk
    if (system.type === 'dust') {
      p.vx += (Math.random() - 0.5) * 0.02;
      p.vy += (Math.random() - 0.5) * 0.02;
      p.vx = Math.max(-0.3, Math.min(0.3, p.vx));
      p.vy = Math.max(-0.2, Math.min(0.2, p.vy));
    }
  }
}

export function drawParticles(
  ctx: CanvasRenderingContext2D,
  system: ParticleSystem,
): void {
  ctx.save();
  for (const p of system.particles) {
    ctx.globalAlpha = p.opacity;
    switch (system.type) {
      case 'rain':
        ctx.strokeStyle = 'rgba(180, 200, 220, 1)';
        ctx.lineWidth = p.size * 0.5;
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(p.x + p.vx * 2, p.y + p.vy * 2);
        ctx.stroke();
        break;
      case 'snow':
        ctx.fillStyle = 'rgba(255, 255, 255, 1)';
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
        break;
      case 'dust':
        ctx.fillStyle = 'rgba(255, 235, 180, 1)';
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
        break;
    }
  }
  ctx.restore();
}
