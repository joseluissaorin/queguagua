/**
 * La portada de queguagua: una parada de guaguas a pie de carretera. Una persona
 * con su cachorro canario levanta el brazo y pregunta «¿qué guagua cojo?». Llega
 * una guagua grande y sonriente, con ojos en el parabrisas y «> queguagua_» en el
 * letrero, que contesta «la de las 8:00». En la tercera ventanilla va un perro
 * con la lengua fuera (guau, guau). Del tubo de escape salen tres nubecitas.
 *
 * Todo en un solo color: el azul ultramarino de un bolígrafo. Cada parte que se
 * mueve es un dibujo aparte con el mismo marco de 960 × 540, para que la página
 * las apile y las anime con fotogramas clave (ruedas, ojos, brazo, perro, humo).
 */
import { type Dibujo, tinta, lapiz, sombra, nota, circulo } from '../motor/boceto';

const ANCHO = 960;
const ALTO = 540;
/** El encuadre que se enseña: de los bocadillos a la carretera. */
export const CAJA = [0, 128, 960, 362] as const;
const marco = { ancho: ANCHO, alto: ALTO, caja: CAJA };
const titulo = 'queguagua';
const descripcion = 'Parte del dibujo de la portada.';

/** Una ventanilla con las esquinas redondeadas, en dos trazos como la haría la mano. */
function ventana(x0: number, x1: number, y0 = 300, y1 = 352) {
  return [
    tinta([[x0 + 2, y1 - 3], [x0, y0 + 6], [x0 + 5, y0], [x1 - 6, y0 - 1], [x1, y0 + 5], [x1 + 1, y1 - 8]], { g: 1.8 }),
    tinta([[x1 + 1, y1 - 8], [x1 - 3, y1], [x0 + 6, y1 + 1], [x0 + 2, y1 - 3]], { g: 1.6 }),
  ];
}

/** Una bocanada de humo: un óvalo que no se cierra del todo y un rizo dentro. */
function bocanada(cx: number, cy: number, r: number) {
  return [
    tinta(circulo([cx, cy], r, 9, 200, 535, r * 0.82), { g: 1.5 }),
    tinta([[cx - r * 0.35, cy + r * 0.1], [cx - r * 0.05, cy - r * 0.3], [cx + r * 0.3, cy - r * 0.05]], { g: 1 }),
  ];
}

/** Una rueda: neumático (dos pasadas), llanta, buje y cinco radios para que se vea girar. */
function rueda(id: string, cx: number, cy: number): Dibujo {
  const radios = [0, 72, 144, 216, 288].map((g) => {
    const a = (g * Math.PI) / 180;
    return tinta([[cx + Math.cos(a) * 6, cy + Math.sin(a) * 6], [cx + Math.cos(a) * 16, cy + Math.sin(a) * 16]], { g: 1.3, recto: true });
  });
  return {
    id, ...marco, titulo, descripcion, duracion: 0.9,
    elementos: [
      tinta(circulo([cx, cy], 30, 16), { g: 2.8, pasadas: 2 }),
      tinta(circulo([cx, cy], 17, 12), { g: 1.7 }),
      tinta(circulo([cx, cy], 4, 6), { g: 1.6 }),
      ...radios,
      // Dos marcas en la goma, para que el giro se note de lejos.
      tinta([[cx - 21, cy - 17], [cx - 25, cy - 12]], { g: 1.4 }),
      tinta([[cx + 21, cy + 17], [cx + 25, cy + 12]], { g: 1.4 }),
    ],
  };
}

export const parada: Dibujo = {
  id: 'parada', ...marco, titulo, descripcion, duracion: 1.4,
  elementos: [
    // La carretera, con regla, y unas briznas.
    lapiz([[16, 469], [944, 466]], { g: 1 }),
    lapiz([[60, 478], [262, 477]], { g: 0.6 }),
    lapiz([[600, 479], [900, 478]], { g: 0.6 }),
    tinta([[34, 469], [37, 461]], { g: 1.1 }), tinta([[40, 469], [44, 459]], { g: 1.1 }), tinta([[46, 469], [48, 463]], { g: 1 }),
    tinta([[268, 469], [271, 462]], { g: 1 }), tinta([[274, 469], [279, 460]], { g: 1.1 }),
    // El poste, en dos líneas, y su pie.
    tinta([[110, 468], [111, 380], [110, 264]], { g: 2.4 }),
    tinta([[119, 468], [120, 380], [119, 264]], { g: 1.5 }),
    tinta([[98, 469], [131, 468]], { g: 2.4, recto: true }),
    // La señal, con una guagüita dibujada dentro.
    tinta([[86, 197], [146, 196], [153, 203], [154, 255], [147, 263], [86, 264], [80, 257], [79, 204], [86, 197]], { g: 2.3 }),
    tinta([[93, 214], [139, 213], [142, 219], [142, 233], [93, 234], [93, 214]], { g: 1.4 }),
    tinta([[97, 221], [136, 220]], { g: 1, recto: true }),
    tinta(circulo([103, 236], 4, 8), { g: 1.3 }),
    tinta(circulo([132, 236], 4, 8), { g: 1.3 }),
    nota(116, 254, 'guaguas', { tam: 12, ancla: 'middle', tinta: 'tinta' }),
  ],
};

export const persona: Dibujo = {
  id: 'persona', ...marco, titulo, descripcion, duracion: 1.4,
  elementos: [
    // La cabeza y el cachorro canario.
    tinta(circulo([205, 331], 17, 12), { g: 2.2 }),
    tinta([[183, 318], [205, 313], [229, 317]], { g: 2.2 }),
    tinta([[191, 316], [193, 302], [206, 298], [218, 302], [220, 315]], { g: 2 }),
    tinta([[193, 309], [219, 308]], { g: 1, recto: true }),
    // Ojos de punto y la boca abierta de quien pregunta.
    tinta([[199, 329], [199.4, 332]], { g: 2.2 }),
    tinta([[211, 329], [211.4, 332]], { g: 2.2 }),
    tinta(circulo([206, 340], 3, 7), { g: 1.2 }),
    // El cuerpo, con chaqueta.
    tinta([[197, 348], [189, 372], [185, 408], [186, 428]], { g: 2.4 }),
    tinta([[214, 348], [222, 372], [226, 408], [224, 428]], { g: 2.4 }),
    tinta([[186, 428], [205, 431], [224, 428]], { g: 2 }),
    tinta([[205, 352], [205, 428]], { g: 1, recto: true, temblor: 0.9 }),
    // Las piernas y los zapatos.
    tinta([[197, 430], [196, 452], [194, 467]], { g: 2.2 }),
    tinta([[214, 430], [215, 452], [217, 467]], { g: 2.2 }),
    tinta([[194, 467], [183, 469]], { g: 2.2 }),
    tinta([[217, 467], [229, 468]], { g: 2.2 }),
    // El brazo que cuelga, con la mano en el bolsillo.
    tinta([[191, 362], [181, 390], [182, 408]], { g: 2 }),
  ],
};

/** El brazo que para la guagua: gira por el hombro. */
export const brazo: Dibujo = {
  id: 'brazo', ...marco, titulo, descripcion, duracion: 0.6,
  elementos: [
    tinta([[219, 360], [236, 344], [246, 318]], { g: 2.2 }),
    tinta(circulo([248, 310], 6, 8), { g: 1.6 }),
    tinta([[244, 305], [242, 296]], { g: 1.2 }),
    tinta([[249, 304], [249, 294]], { g: 1.2 }),
    tinta([[254, 306], [257, 297]], { g: 1.2 }),
  ],
};

export const cuerpo: Dibujo = {
  id: 'cuerpo', ...marco, titulo, descripcion, duracion: 3,
  elementos: [
    // Encaje: la caja de la guagua y el eje de las ruedas.
    lapiz([[330, 256], [886, 256], [886, 440], [330, 440]], { cerrado: true, g: 0.7 }),
    lapiz([[392, 438], [822, 438]], { g: 0.6 }),

    // El techo, la trompa, los bajos con sus pasos de rueda y la trasera.
    tinta([[372, 258], [500, 255], [650, 256], [800, 255], [858, 258]], { g: 2.7, pasadas: 2 }),
    tinta([[372, 258], [352, 264], [342, 280], [338, 320], [337, 380], [339, 420], [346, 436], [360, 441]], { g: 2.7 }),
    tinta([[360, 441], [397, 441]], { g: 2.4 }),
    tinta([[397, 441], [401, 420], [416, 405], [438, 399], [460, 405], [475, 420], [479, 441]], { g: 2.3 }),
    tinta([[479, 441], [600, 440], [735, 440]], { g: 2.4 }),
    tinta([[735, 440], [739, 420], [754, 405], [776, 399], [798, 405], [813, 420], [817, 440]], { g: 2.3 }),
    tinta([[817, 440], [858, 439]], { g: 2.4 }),
    tinta([[858, 258], [874, 266], [882, 290], [884, 380], [882, 425], [872, 437], [858, 439]], { g: 2.7 }),

    // El letrero, con el nombre como en una terminal.
    tinta([[353, 268], [519, 266], [522, 270], [522, 291], [352, 293], [350, 289], [350, 271], [353, 268]], { g: 1.8 }),
    nota(359, 287, '> queguagua_', { tam: 17, tinta: 'tinta' }),

    // El parabrisas (el lado izquierdo es la trompa) y el retrovisor de antena.
    tinta([[344, 301], [404, 299], [410, 305], [412, 366], [406, 374], [341, 377]], { g: 2 }),
    tinta([[341, 296], [327, 288], [321, 300], [329, 305]], { g: 1.6 }),
    // Dos brillos en la esquina del cristal, lejos de los ojos.
    tinta([[402, 352], [394, 366]], { g: 1 }), tinta([[406, 360], [401, 368]], { g: 0.9 }),

    // La sonrisa, con la lengua, el faro y el parachoques.
    tinta([[347, 391], [362, 404], [384, 407], [405, 397]], { g: 2.3 }),
    tinta([[370, 406], [377, 414], [387, 407]], { g: 1.4 }),
    tinta(circulo([353, 421], 7, 10), { g: 1.6 }),
    lapiz([[338, 414], [328, 410]], { g: 0.7 }), lapiz([[338, 422], [326, 422]], { g: 0.7 }), lapiz([[338, 430], [328, 434]], { g: 0.7 }),
    tinta([[335, 432], [374, 433]], { g: 3, recto: true }),

    // Las ventanillas.
    ...ventana(430, 508),
    ...ventana(520, 598),
    ...ventana(610, 688),
    ...ventana(700, 778),
    ...ventana(790, 856),
    // Brillos en dos cristales.
    tinta([[586, 304], [576, 320]], { g: 1 }), tinta([[592, 312], [586, 322]], { g: 0.9 }),
    tinta([[846, 304], [836, 320]], { g: 1 }),

    // Viajeros: una señora con moño en la primera y un señor con gafas en la cuarta.
    tinta(circulo([470, 335], 11, 10), { g: 1.8 }),
    tinta(circulo([474, 321], 5, 7), { g: 1.4 }),
    tinta([[452, 352], [458, 346], [482, 346], [488, 352]], { g: 1.6 }),
    tinta(circulo([740, 334], 11, 10), { g: 1.8 }),
    tinta(circulo([734, 333], 3.5, 6), { g: 1.1 }), tinta(circulo([745, 333], 3.5, 6), { g: 1.1 }),
    tinta([[737, 333], [742, 333]], { g: 1 }),
    tinta([[722, 352], [728, 346], [752, 346], [758, 352]], { g: 1.6 }),

    // La franja, rayada a medias.
    tinta([[438, 376], [600, 375], [870, 374]], { g: 1.6 }),
    tinta([[438, 392], [600, 391], [870, 390]], { g: 1.6 }),
    sombra([[440, 377], [868, 375], [868, 389], [440, 391]], 62, 7, { cobertura: 0.6, g: 0.9 }),

    // La puerta delantera, el piloto y el tubo de escape.
    tinta([[420, 300], [420, 396]], { g: 1.2, recto: true }),
    tinta([[874, 402], [880, 402], [880, 416], [874, 416], [874, 402]], { g: 1.3 }),
    tinta([[848, 446], [886, 447]], { g: 2.8 }),
    tinta(circulo([889, 447], 4, 8), { g: 1.3 }),
    // Una sombra de lápiz en el suelo.
    lapiz([[500, 471], [720, 471]], { g: 0.6 }),
  ],
};

/** Los ojos del parabrisas, con cejas de contento: parpadean y miran a quien pregunta. */
export const ojos: Dibujo = {
  id: 'ojos', ...marco, titulo, descripcion, duracion: 0.9,
  elementos: [
    tinta(circulo([362, 331], 13, 14, 0, 360, 17), { g: 1.9 }),
    tinta(circulo([392, 329], 13, 14, 0, 360, 17), { g: 1.9 }),
    tinta([[350, 307], [362, 302], [374, 307]], { g: 1.7 }),
    tinta([[381, 305], [393, 300], [405, 305]], { g: 1.7 }),
  ],
};

/** Las pupilas, aparte: miran a quien pregunta y, de vez en cuando, a quien lee. */
export const pupilas: Dibujo = {
  id: 'pupilas', ...marco, titulo, descripcion, duracion: 0.5,
  elementos: [
    tinta(circulo([356, 335], 5, 8), { g: 2.4 }),
    tinta(circulo([386, 333], 5, 8), { g: 2.4 }),
    sombra([[352, 331], [360, 331], [360, 339], [352, 339]], 45, 1.6, { g: 1.1 }),
    sombra([[382, 329], [390, 329], [390, 337], [382, 337]], 45, 1.6, { g: 1.1 }),
  ],
};

/** El perro de la tercera ventanilla, con la lengua fuera: menea la cabeza. */
export const perro: Dibujo = {
  id: 'perro', ...marco, titulo, descripcion, duracion: 0.9,
  elementos: [
    tinta([[642, 346], [636, 330], [640, 318], [652, 314], [662, 320], [664, 334], [658, 346]], { g: 1.9 }),
    tinta([[637, 327], [626, 330], [624, 337], [632, 341], [641, 339]], { g: 1.8 }),
    tinta(circulo([625, 332], 2.4, 6), { g: 1.8 }),
    tinta([[655, 316], [667, 318], [671, 332], [665, 341]], { g: 1.8 }),
    tinta([[642, 324], [642.4, 327]], { g: 2.2 }),
    tinta([[630, 340], [631, 348], [637, 347], [636, 340]], { g: 1.3 }),
    tinta([[640, 347], [660, 348]], { g: 1.6 }),
  ],
};

/** Lo que dice el perro, con su flechita de lápiz. */
export const guau: Dibujo = {
  id: 'guau', ...marco, titulo, descripcion, duracion: 0.5,
  elementos: [
    nota(700, 238, 'guau, guau', { tam: 19, giro: -6, tinta: 'tinta' }),
    lapiz([[716, 246], [690, 268], [666, 306]], { recto: false, g: 0.8 }),
  ],
};

export const rueda1 = rueda('rueda1', 438, 438);
export const rueda2 = rueda('rueda2', 776, 438);

export const humo1: Dibujo = { id: 'humo1', ...marco, titulo, descripcion, duracion: 0.4, elementos: bocanada(904, 440, 8) };
export const humo2: Dibujo = { id: 'humo2', ...marco, titulo, descripcion, duracion: 0.4, elementos: bocanada(923, 423, 11) };
export const humo3: Dibujo = { id: 'humo3', ...marco, titulo, descripcion, duracion: 0.4, elementos: bocanada(941, 400, 14) };

export const pregunta: Dibujo = {
  id: 'pregunta', ...marco, titulo, descripcion, duracion: 0.9,
  elementos: [
    tinta([[166, 150], [312, 146], [324, 154], [326, 194], [316, 202], [238, 204], [218, 284], [224, 205], [170, 206], [160, 198], [158, 158], [166, 150]], { g: 2 }),
    nota(242, 173, '¿qué guagua\ncojo?', { tam: 23, ancla: 'middle', tinta: 'tinta' }),
  ],
};

export const respuesta: Dibujo = {
  id: 'respuesta', ...marco, titulo, descripcion, duracion: 0.9,
  elementos: [
    tinta([[402, 156], [570, 152], [582, 160], [584, 200], [574, 208], [474, 210], [450, 262], [458, 210], [406, 212], [396, 204], [394, 164], [402, 156]], { g: 2 }),
    nota(489, 189, 'la de las 8:00', { tam: 23, ancla: 'middle', tinta: 'tinta' }),
  ],
};
