import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import type { Language, Revision, Topic } from './types.ts';
import { dateLabel } from './types.ts';

type Props = {
  topics: Topic[];
  topic: Topic | null;
  transitionTopic: string | null;
  language: Language;
  revisions: Revision[];
  walk: number;
  paused: boolean;
  onWalk: (value: number) => void;
  onTopic: (id: string) => void;
  onEdition: (revision: Revision) => void;
  onFailure: () => void;
};
type Metrics = {
  fps: number;
  frames: number;
  drawCalls: number;
  triangles: number;
  camera: number[];
  activeEditions: number;
};
declare global {
  interface Window {
    __libraryScene?: Metrics;
  }
}
const inks = [
  '#805241',
  '#76664c',
  '#405654',
  '#78715a',
  '#63494a',
  '#a1875b',
  '#3c484c',
];
const cube = new THREE.BoxGeometry(1, 1, 1);
const transform = new THREE.Object3D();
function box(
  group: THREE.Group,
  material: THREE.Material,
  x: number,
  y: number,
  z: number,
  sx: number,
  sy: number,
  sz: number,
) {
  const mesh = new THREE.Mesh(cube, material);
  mesh.position.set(x, y, z);
  mesh.scale.set(sx, sy, sz);
  group.add(mesh);
  return mesh;
}
function labelTexture(title: string, detail: string, index?: number) {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 768;
  const c = canvas.getContext('2d')!;
  c.fillStyle = inks[(index || 0) % inks.length];
  c.fillRect(0, 0, 512, 768);
  c.fillStyle = 'rgba(0,0,0,.16)';
  c.fillRect(0, 0, 25, 768);
  c.fillRect(480, 0, 12, 768);
  c.strokeStyle = '#c6ad7c';
  c.lineWidth = 2;
  c.strokeRect(52, 58, 408, 652);
  c.beginPath();
  c.moveTo(210, 140);
  c.lineTo(256, 94);
  c.lineTo(302, 140);
  c.lineTo(256, 186);
  c.closePath();
  c.stroke();
  c.fillStyle = '#eee2c9';
  c.textAlign = 'center';
  c.font = '46px Georgia';
  const words = title.replace(' (Vyborg)', '').split(' ');
  let lines: string[] = [];
  let line = '';
  words.forEach((word) => {
    if (c.measureText(line + ' ' + word).width > 365 && line) {
      lines.push(line);
      line = word;
    } else line += (line ? ' ' : '') + word;
  });
  lines.push(line);
  lines.forEach((text, i) => c.fillText(text, 256, 310 + i * 58));
  c.fillStyle = '#d8c49b';
  c.font = '22px Georgia';
  c.fillText(detail, 256, 600);
  c.font = '17px sans-serif';
  c.fillText(
    index === undefined
      ? 'EN  ·  FI  ·  SV'
      : 'EDITION ' + String(index + 1).padStart(2, '0'),
    256,
    659,
  );
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}
function book(title: string, detail: string, index?: number) {
  const group = new THREE.Group();
  const texture = labelTexture(title, detail, index);
  const cover = new THREE.MeshStandardMaterial({
    map: texture,
    roughness: 0.88,
  });
  const cloth = new THREE.MeshStandardMaterial({
    color: inks[(index || 0) % inks.length],
    roughness: 0.85,
  });
  const paper = new THREE.MeshStandardMaterial({
    color: '#d6ccb3',
    roughness: 1,
  });
  box(group, paper, 0, 0, 0, 1.34, 1.94, 0.28);
  box(group, cover, 0, 0, 0.165, 1.46, 2.06, 0.045);
  box(group, cloth, 0, 0, -0.165, 1.46, 2.06, 0.045);
  box(group, cloth, -0.71, 0, 0, 0.075, 2.06, 0.36);
  group.userData.dispose = () => {
    texture.dispose();
    cover.dispose();
    cloth.dispose();
    paper.dispose();
  };
  return group;
}
function seeded(index: number) {
  const x = Math.sin(index * 127.1 + 31.7) * 43758.5453;
  return x - Math.floor(x);
}

export default function Scene(props: Props) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef(props);
  live.current = props;
  const labelNodes = useRef(new Map<string, HTMLButtonElement>());
  const [visible, setVisible] = useState<number[]>([]);
  const corridor = Boolean(props.topic);
  useEffect(() => {
    if (!host.current) return;
    const element = host.current;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: false,
        powerPreference: 'high-performance',
      });
    } catch {
      live.current.onFailure();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.6));
    renderer.setSize(element.clientWidth, element.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.25;
    renderer.domElement.setAttribute('aria-hidden', 'true');
    element.prepend(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#111514');
    scene.fog = new THREE.FogExp2('#111514', corridor ? 0.027 : 0.016);
    const camera = new THREE.PerspectiveCamera(
      corridor ? 62 : 52,
      element.clientWidth / element.clientHeight,
      0.1,
      250,
    );
    if (corridor) camera.position.set(0, 1.8, 0);
    else camera.position.set(25, 17, 37);
    camera.lookAt(
      corridor ? new THREE.Vector3(0, 1.7, -12) : new THREE.Vector3(0, 1, 0),
    );
    const hemi = new THREE.HemisphereLight('#bbc5be', '#211a12', 1.8);
    scene.add(hemi);
    const sun = new THREE.DirectionalLight('#f3cf98', 3.5);
    sun.position.set(-15, 30, 18);
    scene.add(sun);
    const cool = new THREE.DirectionalLight('#718b92', 1.4);
    cool.position.set(20, 10, -20);
    scene.add(cool);
    const wood = new THREE.MeshStandardMaterial({
      color: '#35342c',
      roughness: 0.65,
      metalness: 0.22,
    });
    const bronze = new THREE.MeshStandardMaterial({
      color: '#776044',
      roughness: 0.45,
      metalness: 0.48,
    });
    const lightMat = new THREE.MeshBasicMaterial({ color: '#d9b779' });
    const floorMat = new THREE.MeshStandardMaterial({
      color: '#292d29',
      roughness: 0.9,
      metalness: 0.1,
    });
    const architecture = new THREE.Group();
    scene.add(architecture);
    const blocks: { p: number[]; s: number[] }[] = [];
    const volumes: { p: number[]; s: number[]; i: number }[] = [];
    function rack(x: number, z: number, y: number, width = 4.5) {
      blocks.push(
        { p: [x - width / 2, y + 3.1, z], s: [0.15, 6.4, 1.1] },
        { p: [x + width / 2, y + 3.1, z], s: [0.15, 6.4, 1.1] },
      );
      for (let shelf = 0; shelf <= 5; shelf++) {
        blocks.push({ p: [x, y + shelf * 1.22, z], s: [width, 0.13, 1.15] });
        if (shelf < 5)
          for (let b = 0; b < 13; b++) {
            const key = Math.round(
              (x + 70) * 200 + (z + 150) * 20 + y * 11 + shelf * 13 + b,
            );
            const h = 0.62 + seeded(key) * 0.36;
            volumes.push({
              p: [
                x - width / 2 + 0.22 + (b * (width - 0.3)) / 13,
                y + shelf * 1.22 + 0.13 + h / 2,
                z + 0.15,
              ],
              s: [0.18 + seeded(key + 1) * 0.1, h, 0.65],
              i: key,
            });
          }
      }
    }
    if (corridor) {
      box(architecture, floorMat, 0, -0.22, -100, 11, 0.4, 240);
      for (let z = 10; z > -160; z -= 6) {
        for (const side of [-1, 1]) {
          rack(side * 5.9, z, 0, 4.2);
          rack(side * 5.9, z, 6.6, 4.2);
          box(architecture, bronze, side * 3.8, 5.4, z, 0.14, 10.8, 0.18);
          box(architecture, wood, 0, 10.2, z, 8, 0.18, 0.25);
          box(architecture, lightMat, side * 3.8, 3.6, z, 0.055, 0.8, 0.055);
        }
      }
      for (let z = 0; z > -160; z -= 20) {
        const lamp = new THREE.PointLight('#e9b870', 35, 23, 2);
        lamp.position.set(0, 5, z);
        scene.add(lamp);
      }
      const runner = new THREE.Mesh(
        new THREE.PlaneGeometry(2.1, 220),
        new THREE.MeshStandardMaterial({ color: '#45372c', roughness: 1 }),
      );
      runner.rotation.x = -Math.PI / 2;
      runner.position.set(0, 0.002, -95);
      scene.add(runner);
      box(architecture, bronze, -1.08, 0.01, -95, 0.025, 0.015, 220);
      box(architecture, bronze, 1.08, 0.01, -95, 0.025, 0.015, 220);
    } else {
      for (let x = -36; x <= 36; x += 6)
        for (let z = -56; z <= 24; z += 7) {
          if (Math.abs(x) < 20 && z > -22) continue;
          for (const y of [-12, -5, 2, 9, 16]) rack(x, z, y);
        }
      props.topics.forEach((topic, i) => {
        const [x, , z] = topic.position;
        box(architecture, floorMat, x, -0.5, z, 4.6, 0.7, 4.6);
        box(architecture, bronze, x, 0.35, z, 2.2, 1.1, 1.4);
        box(architecture, wood, x, 0.94, z, 2.5, 0.13, 1.7);
        const volume = book(
          topic.title,
          'A HISTORY IN THREE LANGUAGES',
          undefined,
        );
        volume.position.set(x, 2.7, z);
        volume.scale.setScalar(1.65);
        volume.rotation.y = 0.4;
        volume.userData.topicId = topic.id;
        scene.add(volume);
        const lamp = new THREE.PointLight('#f4c98a', 70, 14, 2);
        lamp.position.set(x, 5, z + 2);
        scene.add(lamp);
        const beam = new THREE.Mesh(
          new THREE.CylinderGeometry(0.12, 2.6, 22, 16, 1, true),
          new THREE.MeshBasicMaterial({
            color: '#e0c28c',
            transparent: true,
            opacity: 0.025,
            depthWrite: false,
            side: THREE.DoubleSide,
            blending: THREE.AdditiveBlending,
          }),
        );
        beam.position.set(x, 12, z);
        scene.add(beam);
        if (i < props.topics.length - 1) {
          const next = props.topics[i + 1].position;
          const from = new THREE.Vector3(x, -0.85, z),
            to = new THREE.Vector3(next[0], -0.85, next[2]);
          const direction = to.clone().sub(from);
          const bridge = new THREE.Mesh(
            new THREE.BoxGeometry(0.65, 0.08, direction.length()),
            wood,
          );
          bridge.position.copy(from.clone().add(to).multiplyScalar(0.5));
          bridge.quaternion.setFromUnitVectors(
            new THREE.Vector3(0, 0, 1),
            direction.normalize(),
          );
          scene.add(bridge);
        }
      });
    }
    const beams = new THREE.InstancedMesh(cube, wood, blocks.length);
    blocks.forEach((b, i) => {
      transform.position.fromArray(b.p);
      transform.scale.fromArray(b.s);
      transform.rotation.set(0, 0, 0);
      transform.updateMatrix();
      beams.setMatrixAt(i, transform.matrix);
    });
    beams.instanceMatrix.needsUpdate = true;
    architecture.add(beams);
    const books = new THREE.InstancedMesh(
      cube,
      new THREE.MeshStandardMaterial({ roughness: 0.92 }),
      volumes.length,
    );
    volumes.forEach((b, i) => {
      transform.position.fromArray(b.p);
      transform.scale.fromArray(b.s);
      transform.updateMatrix();
      books.setMatrixAt(i, transform.matrix);
      books.setColorAt(
        i,
        new THREE.Color(inks[Math.floor(seeded(b.i + 8) * inks.length)]),
      );
    });
    books.instanceMatrix.needsUpdate = true;
    architecture.add(books);
    const particles = new THREE.BufferGeometry();
    const positions = new Float32Array(700 * 3);
    for (let i = 0; i < 700; i++) {
      positions[i * 3] = (seeded(i * 3) - 0.5) * 80;
      positions[i * 3 + 1] = seeded(i * 3 + 1) * 28 - 5;
      positions[i * 3 + 2] = (seeded(i * 3 + 2) - 0.5) * 140;
    }
    particles.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const dust = new THREE.Points(
      particles,
      new THREE.PointsMaterial({
        color: '#d6c29c',
        size: 0.045,
        transparent: true,
        opacity: 0.35,
        depthWrite: false,
      }),
    );
    scene.add(dust);
    const editions = new THREE.Group();
    scene.add(editions);
    let windowStart = -100;
    function editionWindow(center: number) {
      const first = Math.max(0, Math.floor(center / 6) * 6 - 6);
      if (first === windowStart) return;
      windowStart = first;
      editions.children.forEach((child) => child.userData.dispose?.());
      editions.clear();
      const indices = [];
      for (
        let i = first;
        i < Math.min(live.current.revisions.length, first + 28);
        i++
      ) {
        const revision = live.current.revisions[i];
        const side = i % 2 === 0 ? -1 : 1;
        const z = -Math.floor(i / 2) * 5 - 5;
        const volume = book(
          live.current.topic!.articles[live.current.language].title,
          dateLabel(revision.timestamp) + ' · r' + revision.revision_id,
          i,
        );
        volume.position.set(side * 2.5, 1.9, z);
        volume.rotation.y = -side * 0.55;
        volume.userData.revisionId = revision.revision_id;
        editions.add(volume);
        box(editions, bronze, side * 2.5, 0.65, z, 1.9, 0.15, 1.5);
        indices.push(i);
      }
      setVisible(indices);
    }
    if (corridor) editionWindow(live.current.walk);
    else setVisible([]);
    let frame = 0,
      last = 0,
      activeMilliseconds = 0,
      activeFrames = 0,
      lastPaused = false,
      lastTelemetry = 0;
    let overviewDrift = 0;
    const projected = new THREE.Vector3();
    function project(key: string, position: THREE.Vector3, nearby = true) {
      const label = labelNodes.current.get(key);
      if (!label) return;
      projected.copy(position).project(camera);
      const visible =
        nearby &&
        projected.z > -1 &&
        projected.z < 1 &&
        Math.abs(projected.x) < 1.15 &&
        Math.abs(projected.y) < 1.15;
      label.style.opacity = visible ? '1' : '0';
      label.style.pointerEvents = visible ? 'auto' : 'none';
      label.style.visibility = visible ? 'visible' : 'hidden';
      label.style.transform = `translate(-50%,-50%) translate(${(projected.x * 0.5 + 0.5) * element.clientWidth}px,${(-projected.y * 0.5 + 0.5) * element.clientHeight}px)`;
    }
    function animate(now: number) {
      frame = requestAnimationFrame(animate);
      const state = live.current,
        elapsed = last ? Math.max(0, now - last) : 0,
        dt = Math.min(elapsed / 1000, 0.1);
      last = now;
      if (state.paused && !lastPaused && corridor) {
        state.onWalk(
          Math.max(
            0,
            Math.min(state.revisions.length - 1, -camera.position.z / 2.5),
          ),
        );
      }
      lastPaused = state.paused;
      if (!state.paused) {
        const alpha = 1 - Math.exp(-dt * 4.2);
        if (corridor) {
          const max = Math.max(0, state.revisions.length - 1);
          const progress = Math.max(0, Math.min(state.walk, max));
          camera.position.lerp(
            new THREE.Vector3(0, 1.8, -progress * 2.5),
            alpha,
          );
          camera.lookAt(0, 1.75, camera.position.z - 14);
          editionWindow(progress);
        } else {
          const destination = state.topics.find(
            (row) => row.id === state.transitionTopic,
          );
          if (destination) {
            camera.position.lerp(
              new THREE.Vector3(
                destination.position[0] + 1.1,
                3.8,
                destination.position[2] + 4.2,
              ),
              1 - Math.exp(-dt * 6),
            );
            camera.lookAt(
              destination.position[0],
              2.6,
              destination.position[2],
            );
          } else {
            camera.position.lerp(
              new THREE.Vector3(
                25 + Math.sin(now * 0.00007) * 0.8,
                17,
                37 - overviewDrift * 8,
              ),
              alpha,
            );
            camera.lookAt(0, 1, 0);
          }
        }
        renderer.render(scene, camera);
        activeFrames++;
        activeMilliseconds += elapsed;
      }
      if (corridor) {
        const nearestRow = Math.floor(state.walk / 2);
        visibleKeys().forEach((i) => {
          const side = i % 2 === 0 ? -1 : 1;
          project(
            'revision-' + i,
            new THREE.Vector3(side * 2.5, 0.42, -Math.floor(i / 2) * 5 - 4.9),
            Math.floor(i / 2) === nearestRow,
          );
        });
      } else
        state.topics.forEach((topic) =>
          project(
            topic.id,
            new THREE.Vector3(topic.position[0], 0.02, topic.position[2] + 1.2),
          ),
        );
      window.__libraryScene = {
        fps: activeMilliseconds
          ? activeFrames / (activeMilliseconds / 1000)
          : 0,
        frames: activeFrames,
        drawCalls: renderer.info.render.calls,
        triangles: renderer.info.render.triangles,
        camera: camera.position.toArray(),
        activeEditions: editions.children.length / 2,
      };
      if (now - lastTelemetry > 500) {
        renderer.domElement.dataset.frames = String(activeFrames);
        renderer.domElement.dataset.activeMs = String(
          Math.round(activeMilliseconds),
        );
        renderer.domElement.dataset.fps = activeMilliseconds
          ? (activeFrames / (activeMilliseconds / 1000)).toFixed(1)
          : '0';
        renderer.domElement.dataset.camera = camera.position
          .toArray()
          .map((value) => value.toFixed(6))
          .join(',');
        renderer.domElement.dataset.activeEditions = String(
          editions.children.length / 2,
        );
        renderer.domElement.dataset.drawCalls = String(
          renderer.info.render.calls,
        );
        lastTelemetry = now;
      }
    }
    function visibleKeys() {
      const first = Math.max(0, windowStart);
      return Array.from(
        {
          length: Math.max(
            0,
            Math.min(live.current.revisions.length - first, 28),
          ),
        },
        (_, i) => first + i,
      );
    }
    function wheel(event: WheelEvent) {
      if (live.current.paused) return;
      event.preventDefault();
      if (corridor)
        live.current.onWalk(
          Math.max(
            0,
            Math.min(
              live.current.revisions.length - 1,
              live.current.walk + event.deltaY / 190,
            ),
          ),
        );
      else
        overviewDrift = THREE.MathUtils.clamp(
          overviewDrift + event.deltaY / 1500,
          -0.6,
          1.3,
        );
    }
    element.addEventListener('wheel', wheel, { passive: false });
    const resize = new ResizeObserver(() => {
      camera.aspect = element.clientWidth / element.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(element.clientWidth, element.clientHeight);
      renderer.render(scene, camera);
    });
    resize.observe(element);
    const failure = (event: Event) => {
      event.preventDefault();
      live.current.onFailure();
    };
    renderer.domElement.addEventListener('webglcontextlost', failure);
    renderer.render(scene, camera);
    frame = requestAnimationFrame(animate);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      element.removeEventListener('wheel', wheel);
      renderer.domElement.removeEventListener('webglcontextlost', failure);
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh;
        if (mesh.geometry && mesh.geometry !== cube) mesh.geometry.dispose();
        if (mesh.material) {
          const materials = Array.isArray(mesh.material)
            ? mesh.material
            : [mesh.material];
          materials.forEach((material) => {
            (material as THREE.MeshStandardMaterial).map?.dispose();
            material.dispose();
          });
        }
      });
      renderer.dispose();
      renderer.domElement.remove();
      labelNodes.current.clear();
    };
  }, [corridor, props.topic?.id, props.language, props.revisions.length]);
  return (
    <div className={'scene ' + (corridor ? 'scene-corridor' : '')} ref={host}>
      <div className="scene-labels">
        {!corridor
          ? props.topics.map((topic) => (
              <button
                key={topic.id}
                className="world-label"
                ref={(node) => {
                  if (node) labelNodes.current.set(topic.id, node);
                  else labelNodes.current.delete(topic.id);
                }}
                onClick={() => props.onTopic(topic.id)}
                aria-label={'Enter ' + topic.title + ' history'}
              >
                <span>{topic.articles[props.language].title}</span>
                <small>
                  Enter its history <span aria-hidden="true">↗</span>
                </small>
              </button>
            ))
          : visible.map((i) => {
              const revision = props.revisions[i];
              return revision ? (
                <button
                  key={revision.revision_id}
                  ref={(node) => {
                    if (node) labelNodes.current.set('revision-' + i, node);
                    else labelNodes.current.delete('revision-' + i);
                  }}
                  className="edition-label"
                  onClick={() => props.onEdition(revision)}
                  aria-label={
                    'Open edition ' +
                    (i + 1) +
                    ', ' +
                    dateLabel(revision.timestamp)
                  }
                >
                  <span>{dateLabel(revision.timestamp)}</span>
                  <small>
                    Edition {String(i + 1).padStart(2, '0')} · r
                    {revision.revision_id}
                  </small>
                </button>
              ) : null;
            })}
      </div>
    </div>
  );
}
