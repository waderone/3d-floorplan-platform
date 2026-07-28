const stage = document.querySelector(".stage");
const panoramaView = document.querySelector('[data-view="panorama"]');
const canvas = document.querySelector("#panorama-canvas");
const copyAddress = document.querySelector("#copy-address");
const loadingStatus = document.querySelector(".loading");
const modeButtons = [...document.querySelectorAll("[data-mode]")];
const views = [...document.querySelectorAll("[data-view]")];

let panorama;
let activeMode = "hero";
let heroReady = false;

function updateLoadingState() {
  const panoramaReady =
    panorama?.ready || panoramaView.classList.contains("has-fallback");
  const ready = activeMode === "hero" ? heroReady : panoramaReady;
  stage.classList.toggle("is-ready", Boolean(ready));
  loadingStatus.hidden = Boolean(ready);
}

function switchMode(mode) {
  activeMode = mode;
  for (const button of modeButtons) {
    const active = button.dataset.mode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  for (const view of views) {
    const active = view.dataset.view === mode;
    view.classList.toggle("is-visible", active);
    view.setAttribute("aria-hidden", String(!active));
  }
  if (mode === "panorama") {
    panorama?.resize();
    panorama?.draw();
  }
  updateLoadingState();
}

for (const button of modeButtons) {
  button.addEventListener("click", () => switchMode(button.dataset.mode));
}

async function copyCurrentAddress() {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(location.href);
      return;
    } catch {
      // 局域网 HTTP 页面可能暴露 Clipboard API，但仍拒绝写入。
    }
  }
  const value = document.createElement("textarea");
  value.value = location.href;
  value.style.position = "fixed";
  value.style.opacity = "0";
  document.body.append(value);
  value.select();
  const copied = document.execCommand("copy");
  value.remove();
  if (!copied) throw new Error("copy failed");
}

copyAddress.addEventListener("click", async () => {
  try {
    await copyCurrentAddress();
    copyAddress.textContent = "地址已复制";
  } catch {
    copyAddress.textContent = "请复制浏览器地址";
  }
  window.setTimeout(() => {
    copyAddress.textContent = "复制当前地址";
  }, 1800);
});

class PanoramaRenderer {
  constructor(target, imageUrl) {
    this.canvas = target;
    this.gl = target.getContext("webgl2", {
      alpha: false,
      antialias: true,
      powerPreference: "high-performance",
    });
    if (!this.gl) {
      throw new Error("当前浏览器不支持高质量全景");
    }
    this.yaw = 0;
    this.pitch = 0;
    this.fov = Math.PI / 2.25;
    this.pointers = new Map();
    this.lastDistance = null;
    this.program = this.createProgram();
    this.texture = this.gl.createTexture();
    this.bindEvents();
    this.load(imageUrl);
  }

  createShader(type, source) {
    const shader = this.gl.createShader(type);
    this.gl.shaderSource(shader, source);
    this.gl.compileShader(shader);
    if (!this.gl.getShaderParameter(shader, this.gl.COMPILE_STATUS)) {
      throw new Error(this.gl.getShaderInfoLog(shader) || "全景着色器编译失败");
    }
    return shader;
  }

  createProgram() {
    const vertex = this.createShader(
      this.gl.VERTEX_SHADER,
      `#version 300 es
      in vec2 aPosition;
      void main() {
        gl_Position = vec4(aPosition, 0.0, 1.0);
      }`,
    );
    const fragment = this.createShader(
      this.gl.FRAGMENT_SHADER,
      `#version 300 es
      precision highp float;
      uniform sampler2D uPanorama;
      uniform vec2 uResolution;
      uniform float uYaw;
      uniform float uPitch;
      uniform float uFov;
      out vec4 outColor;

      mat3 rotateX(float angle) {
        float c = cos(angle);
        float s = sin(angle);
        return mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c);
      }

      mat3 rotateY(float angle) {
        float c = cos(angle);
        float s = sin(angle);
        return mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c);
      }

      void main() {
        vec2 point = (gl_FragCoord.xy / uResolution) * 2.0 - 1.0;
        point.x *= uResolution.x / uResolution.y;
        vec3 ray = normalize(vec3(point * tan(uFov * 0.5), 1.0));
        ray = rotateY(uYaw) * rotateX(uPitch) * ray;
        float longitude = atan(ray.x, ray.z);
        float latitude = asin(clamp(ray.y, -1.0, 1.0));
        vec2 uv = vec2(longitude / 6.28318530718 + 0.5, 0.5 - latitude / 3.14159265359);
        outColor = texture(uPanorama, uv);
      }`,
    );
    const program = this.gl.createProgram();
    this.gl.attachShader(program, vertex);
    this.gl.attachShader(program, fragment);
    this.gl.linkProgram(program);
    if (!this.gl.getProgramParameter(program, this.gl.LINK_STATUS)) {
      throw new Error(this.gl.getProgramInfoLog(program) || "全景程序链接失败");
    }
    this.gl.useProgram(program);
    const buffer = this.gl.createBuffer();
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, buffer);
    this.gl.bufferData(
      this.gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      this.gl.STATIC_DRAW,
    );
    const position = this.gl.getAttribLocation(program, "aPosition");
    this.gl.enableVertexAttribArray(position);
    this.gl.vertexAttribPointer(position, 2, this.gl.FLOAT, false, 0, 0);
    this.uniforms = {
      resolution: this.gl.getUniformLocation(program, "uResolution"),
      yaw: this.gl.getUniformLocation(program, "uYaw"),
      pitch: this.gl.getUniformLocation(program, "uPitch"),
      fov: this.gl.getUniformLocation(program, "uFov"),
      panorama: this.gl.getUniformLocation(program, "uPanorama"),
    };
    return program;
  }

  load(url) {
    const image = new Image();
    image.decoding = "async";
    image.addEventListener("load", () => {
      const maximum = this.gl.getParameter(this.gl.MAX_TEXTURE_SIZE);
      if (image.naturalWidth > maximum || image.naturalHeight > maximum) {
        panoramaView.classList.add("has-fallback");
        return;
      }
      this.gl.bindTexture(this.gl.TEXTURE_2D, this.texture);
      this.gl.texParameteri(this.gl.TEXTURE_2D, this.gl.TEXTURE_WRAP_S, this.gl.REPEAT);
      this.gl.texParameteri(this.gl.TEXTURE_2D, this.gl.TEXTURE_WRAP_T, this.gl.CLAMP_TO_EDGE);
      this.gl.texParameteri(this.gl.TEXTURE_2D, this.gl.TEXTURE_MIN_FILTER, this.gl.LINEAR);
      this.gl.texParameteri(this.gl.TEXTURE_2D, this.gl.TEXTURE_MAG_FILTER, this.gl.LINEAR);
      this.gl.texImage2D(
        this.gl.TEXTURE_2D,
        0,
        this.gl.RGB,
        this.gl.RGB,
        this.gl.UNSIGNED_BYTE,
        image,
      );
      this.gl.uniform1i(this.uniforms.panorama, 0);
      this.ready = true;
      this.resize();
      this.draw();
      updateLoadingState();
    });
    image.addEventListener("error", () => {
      panoramaView.classList.add("has-fallback");
      updateLoadingState();
    });
    image.src = url;
  }

  bindEvents() {
    this.canvas.addEventListener("pointerdown", (event) => {
      this.canvas.setPointerCapture(event.pointerId);
      this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      this.lastDistance = this.pointerDistance();
      panoramaView.classList.add("has-interacted");
    });
    this.canvas.addEventListener("pointermove", (event) => {
      const previous = this.pointers.get(event.pointerId);
      if (!previous) return;
      this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (this.pointers.size >= 2) {
        const distance = this.pointerDistance();
        if (this.lastDistance && distance) {
          this.fov = Math.max(
            0.62,
            Math.min(1.65, this.fov - (distance - this.lastDistance) * 0.0025),
          );
        }
        this.lastDistance = distance;
      } else {
        this.yaw -= (event.clientX - previous.x) * 0.004;
        this.pitch = Math.max(
          -1.35,
          Math.min(1.35, this.pitch + (event.clientY - previous.y) * 0.003),
        );
      }
      this.draw();
    });
    const endPointer = (event) => {
      this.pointers.delete(event.pointerId);
      this.lastDistance = this.pointerDistance();
    };
    this.canvas.addEventListener("pointerup", endPointer);
    this.canvas.addEventListener("pointercancel", endPointer);
    this.canvas.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        this.fov = Math.max(0.62, Math.min(1.65, this.fov + event.deltaY * 0.0007));
        panoramaView.classList.add("has-interacted");
        this.draw();
      },
      { passive: false },
    );
    this.canvas.addEventListener("keydown", (event) => {
      const rotation = 0.08;
      if (event.key === "ArrowLeft") this.yaw += rotation;
      else if (event.key === "ArrowRight") this.yaw -= rotation;
      else if (event.key === "ArrowUp") this.pitch = Math.max(-1.35, this.pitch - rotation);
      else if (event.key === "ArrowDown") this.pitch = Math.min(1.35, this.pitch + rotation);
      else if (event.key === "+" || event.key === "=") {
        this.fov = Math.max(0.62, this.fov - rotation);
      } else if (event.key === "-") {
        this.fov = Math.min(1.65, this.fov + rotation);
      } else {
        return;
      }
      event.preventDefault();
      panoramaView.classList.add("has-interacted");
      this.draw();
    });
    window.addEventListener("resize", () => {
      this.resize();
      this.draw();
    });
  }

  pointerDistance() {
    if (this.pointers.size < 2) return null;
    const [first, second] = [...this.pointers.values()];
    return Math.hypot(second.x - first.x, second.y - first.y);
  }

  resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.floor(this.canvas.clientWidth * ratio));
    const height = Math.max(1, Math.floor(this.canvas.clientHeight * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
      this.gl.viewport(0, 0, width, height);
    }
  }

  draw() {
    if (!this.ready) return;
    this.gl.useProgram(this.program);
    this.gl.uniform2f(this.uniforms.resolution, this.canvas.width, this.canvas.height);
    this.gl.uniform1f(this.uniforms.yaw, this.yaw);
    this.gl.uniform1f(this.uniforms.pitch, this.pitch);
    this.gl.uniform1f(this.uniforms.fov, this.fov);
    this.gl.drawArrays(this.gl.TRIANGLES, 0, 3);
  }
}

const heroImage = document.querySelector(".hero-view img");
const reveal = () => {
  heroReady = true;
  updateLoadingState();
};
heroImage.addEventListener("load", reveal, { once: true });
heroImage.addEventListener("error", reveal, { once: true });
if (heroImage.complete) reveal();

try {
  panorama = new PanoramaRenderer(canvas, "./media/panorama-8k.jpg");
} catch (error) {
  console.warn(error);
  panoramaView.classList.add("has-fallback");
  updateLoadingState();
}
