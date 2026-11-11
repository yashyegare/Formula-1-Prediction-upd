import * as THREE from "three";

export interface CircuitScene {
  rotate: (direction: number) => void;
  reset: () => void;
  setPaused: (paused: boolean) => void;
  dispose: () => void;
}

/** A schematic ribbon, rendered only during interaction or a short transition. */
export function createCircuitScene(
  host: HTMLElement,
  outline: string,
  paused: boolean,
  onError: () => void
): CircuitScene {
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x101720, 1);
  renderer.domElement.setAttribute("aria-hidden", "true");
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  camera.position.set(0, 7.5, 7.5);
  camera.lookAt(0, 0, 0);
  const group = new THREE.Group();
  scene.add(group);
  scene.add(new THREE.HemisphereLight(0xe7efff, 0x172033, 3));
  const light = new THREE.DirectionalLight(0xffd5ca, 4);
  light.position.set(4, 8, 2);
  scene.add(light);
  const points = outline
    .trim()
    .split(/\s+/)
    .map((pair) => {
      const [x, y] = pair.split(",").map(Number);
      return new THREE.Vector3(
        ((x ?? 160) - 160) / 50,
        0.08,
        ((y ?? 90) - 90) / 50
      );
    });
  if (
    points.length < 3 ||
    points.some((point) => !Number.isFinite(point.x + point.z))
  ) {
    renderer.dispose();
    renderer.domElement.remove();
    throw new Error("Invalid circuit outline");
  }
  // Remove a repeated endpoint before building the closed curve.
  if (points[0]!.distanceTo(points[points.length - 1]!) < 0.001) points.pop();
  const curve = new THREE.CatmullRomCurve3(points, true, "centripetal");
  const radius = Math.max(...points.map((point) => point.length())) + 0.12;
  const samples = curve.getPoints(320);
  const positions: number[] = [];
  const vertex = (
    p: THREE.Vector3,
    nx: number,
    nz: number,
    side: number,
    height: number
  ) => [p.x + nx * side * 0.055, height, p.z + nz * side * 0.055];
  for (let i = 0; i < samples.length - 1; i++) {
    const a = samples[i]!;
    const b = samples[i + 1]!;
    const tangent = b.clone().sub(a).normalize();
    const left = vertex(a, -tangent.z, tangent.x, 1, 0.08);
    const right = vertex(a, -tangent.z, tangent.x, -1, 0.08);
    const nextLeft = vertex(b, -tangent.z, tangent.x, 1, 0.08);
    const nextRight = vertex(b, -tangent.z, tangent.x, -1, 0.08);
    positions.push(
      ...left,
      ...nextLeft,
      ...right,
      ...right,
      ...nextLeft,
      ...nextRight
    );
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3)
  );
  geometry.computeVertexNormals();
  const material = new THREE.MeshStandardMaterial({
    color: 0xaebfd6,
    metalness: 0.35,
    roughness: 0.48,
    side: THREE.DoubleSide,
  });
  group.add(new THREE.Mesh(geometry, material));
  const railGeometry = new THREE.TubeGeometry(curve, 320, 0.009, 4, true);
  const railMaterial = new THREE.MeshBasicMaterial({ color: 0xff796a });
  group.add(new THREE.Mesh(railGeometry, railMaterial));
  const grid = new THREE.GridHelper(9, 18, 0x2a394d, 0x1a2738);
  grid.position.y = -0.03;
  scene.add(grid);

  let disposed = false,
    visible = true,
    frame = 0,
    tween = 0;
  let reduced =
    paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let drag: { x: number; yaw: number; id: number } | null = null;
  const canRender = () => !disposed && visible && !document.hidden;
  const requestRender = () => {
    if (!canRender() || frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (canRender()) renderer.render(scene, camera);
    });
  };
  const stopTween = () => {
    cancelAnimationFrame(tween);
    tween = 0;
  };
  const goTo = (target: number) => {
    stopTween();
    if (reduced || !canRender()) {
      group.rotation.y = target;
      requestRender();
      return;
    }
    const start = group.rotation.y;
    const began = performance.now();
    const tick = (now: number) => {
      if (!canRender()) {
        group.rotation.y = target;
        tween = 0;
        return;
      }
      const progress = Math.min((now - began) / 550, 1);
      group.rotation.y =
        start + (target - start) * (1 - Math.pow(1 - progress, 3));
      requestRender();
      tween = progress < 1 ? requestAnimationFrame(tick) : 0;
    };
    tween = requestAnimationFrame(tick);
  };
  const resize = () => {
    const { width, height } = host.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    const vertical = THREE.MathUtils.degToRad(camera.fov);
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * camera.aspect);
    const distance =
      (radius / Math.sin(Math.min(vertical, horizontal) / 2)) * 1.05;
    camera.position.set(0, 0.75, 0.85).normalize().multiplyScalar(distance);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    requestRender();
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(host);
  const visibilityObserver = new IntersectionObserver(([entry]) => {
    visible = entry?.isIntersecting ?? false;
    if (!visible) {
      stopTween();
      cancelAnimationFrame(frame);
      frame = 0;
    } else requestRender();
  });
  visibilityObserver.observe(host);
  const visibilityChange = () => {
    if (document.hidden) {
      stopTween();
      cancelAnimationFrame(frame);
      frame = 0;
    } else requestRender();
  };
  const down = (event: PointerEvent) => {
    if (event.button !== 0) return;
    stopTween();
    drag = { x: event.clientX, yaw: group.rotation.y, id: event.pointerId };
    host.setPointerCapture(event.pointerId);
    host.dataset.dragging = "true";
  };
  const move = (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.id) return;
    group.rotation.y = drag.yaw + (event.clientX - drag.x) * 0.012;
    requestRender();
  };
  const up = () => {
    drag = null;
    host.dataset.dragging = "false";
  };
  const contextLost = (event: Event) => {
    event.preventDefault();
    if (!disposed) onError();
  };
  host.addEventListener("pointerdown", down);
  host.addEventListener("pointermove", move);
  host.addEventListener("pointerup", up);
  host.addEventListener("pointercancel", up);
  renderer.domElement.addEventListener("webglcontextlost", contextLost);
  document.addEventListener("visibilitychange", visibilityChange);
  resize();
  group.rotation.y = -0.2;
  goTo(0);
  return {
    rotate: (direction) => goTo(group.rotation.y + (direction * Math.PI) / 6),
    reset: () => goTo(0),
    setPaused: (value) => {
      reduced = value;
      if (value) {
        stopTween();
        requestRender();
      }
    },
    dispose: () => {
      disposed = true;
      stopTween();
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      visibilityObserver.disconnect();
      host.removeEventListener("pointerdown", down);
      host.removeEventListener("pointermove", move);
      host.removeEventListener("pointerup", up);
      host.removeEventListener("pointercancel", up);
      document.removeEventListener("visibilitychange", visibilityChange);
      renderer.domElement.removeEventListener("webglcontextlost", contextLost);
      geometry.dispose();
      material.dispose();
      railGeometry.dispose();
      railMaterial.dispose();
      grid.geometry.dispose();
      (grid.material as THREE.Material).dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    },
  };
}
