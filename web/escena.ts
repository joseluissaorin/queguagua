/**
 * La escena de la portada, montada en capas: cada parte que se mueve es un SVG
 * aparte con el mismo marco de 960 × 540, apilado encima de los demás. La pluma
 * las dibuja en orden (cada una con su `espera`) y, cuando termina, las capas
 * se mueven con fotogramas clave (ver `escena.css`).
 */
import { aSvg, type Dibujo } from './motor/boceto';
import * as g from './dibujos/guagua';

/** Cuándo empieza la pluma con cada parte, en segundos. */
const orden: [Dibujo, number, string][] = [
  [g.parada, 0, 'parada'],
  [g.persona, 0.4, 'persona'],
  [g.brazo, 1.5, 'brazo'],
  [g.cuerpo, 1.1, 'cuerpo'],
  [g.rueda1, 3.3, 'rueda r1'],
  [g.rueda2, 3.5, 'rueda r2'],
  [g.ojos, 3.8, 'ojos'],
  [g.pupilas, 4.4, 'pupilas'],
  [g.perro, 4.3, 'perro'],
  [g.guau, 5, 'guau'],
  [g.humo1, 4.7, 'humo h1'],
  [g.humo2, 4.85, 'humo h2'],
  [g.humo3, 5, 'humo h3'],
  [g.pregunta, 5.2, 'pregunta'],
  [g.respuesta, 6, 'respuesta'],
];

/** Dónde gira o se apoya cada parte, en unidades del dibujo (se pasa a % del encuadre). */
const pivotes: Record<string, [number, number]> = {
  guagua: [610, 440], caja: [610, 440], brazo: [219, 360], ojos: [377, 330], pupilas: [377, 330],
  perro: [650, 346], r1: [438, 438], r2: [776, 438], h1: [904, 440], h2: [924, 424], h3: [942, 402],
  guau: [730, 236], pregunta: [242, 176], respuesta: [489, 182],
};
const [CX, CY, CW, CH] = g.CAJA;
const origen = (clase: string) => {
  const p = pivotes[clase.split(' ').at(-1)!] ?? pivotes[clase.split(' ')[0]];
  if (!p) return '';
  const x = ((p[0] - CX) / CW) * 100, y = ((p[1] - CY) / CH) * 100;
  return ` style="transform-origin:${x.toFixed(2)}% ${y.toFixed(2)}%"`;
};
const div = (clase: string, dentro: string) => `<div class="capa ${clase}"${origen(clase)}>${dentro}</div>`;

const capa = (nombre: string) => {
  const e = orden.find(([, , c]) => c.split(' ')[0] === nombre || c === nombre);
  if (!e) throw new Error(nombre);
  const [d, espera, clase] = e;
  return div(clase, aSvg(d, { espera, decorativo: true }));
};

export function escena(): string {
  const etiqueta =
    'Dibujo a bolígrafo azul: en una parada de guaguas, una persona con cachorro canario levanta el brazo y ' +
    'pregunta «¿qué guagua cojo?». Una guagua sonriente, con ojos en el parabrisas y «> queguagua_» en el ' +
    'letrero, contesta «la de las 8:00». En una ventanilla va un perro con la lengua fuera: «guau, guau».';
  return [
    `<figure class="escena" role="img" aria-label="${etiqueta}" style="aspect-ratio:${CW}/${CH}">`,
    capa('parada'),
    capa('persona'),
    capa('brazo'),
    `<div class="capa guagua"${origen('guagua')}>`,
    div('caja', capa('cuerpo') + capa('ojos') + capa('pupilas') + capa('perro')),
    orden.filter(([, , c]) => c.startsWith('rueda')).map(([d, e, c]) => div(c, aSvg(d, { espera: e, decorativo: true }))).join(''),
    orden.filter(([, , c]) => c.startsWith('humo')).map(([d, e, c]) => div(c, aSvg(d, { espera: e, decorativo: true }))).join(''),
    `</div>`,
    capa('guau'),
    capa('pregunta'),
    capa('respuesta'),
    `</figure>`,
  ].join('');
}

/** Cuánto tarda la pluma en terminar la escena entera (las animaciones empiezan después). */
export const FIN_DIBUJO = 6.9 * 0.4; // con --ritmo .4 (escena.css)
