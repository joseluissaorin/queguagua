/**
 * Genera la web de queguagua en `dist/`: una sola página estática, con la escena
 * dibujada a pluma (en ultramarino) y el CSS y el JS en línea.
 *   npx tsx build.ts
 */
import { mkdirSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs';
import { escena } from './escena';

const aqui = new URL('.', import.meta.url).pathname;
const dist = aqui + 'dist/';
mkdirSync(dist + 'fuentes', { recursive: true });
copyFileSync(aqui + 'publico/fuentes/mano.woff2', dist + 'fuentes/mano.woff2');
copyFileSync(aqui + 'publico/fuentes/OFL.txt', dist + 'fuentes/OFL.txt');

const css = [readFileSync(aqui + 'motor/dibujos.css', 'utf8'), readFileSync(aqui + 'escena.css', 'utf8'), readFileSync(aqui + 'pagina.css', 'utf8')]
  .join('\n')
  // La letra de mano va dentro de la página (unos 16 KB): la web funciona sola, sin otra petición.
  .replace("url('/fuentes/mano.woff2')", `url(data:font/woff2;base64,${readFileSync(aqui + 'publico/fuentes/mano.woff2').toString('base64')})`)
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/\n\s*\n/g, '\n');

const esc = (t: string) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const busqueda = `$ qg alsa search Granada Madrid -d 2026-12-04 --after 07:00 -n 1 --abono
{
  "trip": "one_way",
  "promo": { "abono_unico": true, "valid": true },
  "journeys": [
    {
      "departure": "2026-12-04T07:00:00+01:00",
      "arrival": "2026-12-04T12:00:00+01:00",
      "service": ["Comfort"],
      "available": true,
      "fares": [{ "name": "Abono Único", "price": 0.0 }]
    }
  ]
}`;

const compra = `$ qg alsa buy Granada Madrid -d 2026-12-04 -t 08:00 \\
    --seat-pref window --extra insurance
{
  "status": "reviewed",
  "quote": {
    "package": { "name": "Flexible" },
    "seats": [{ "seat": 107 }],
    "management_fee": 0.0,
    "total": 25.53
  },
  "saved_card": { "type": "MasterCard", "last4": "1234" },
  "next": "Nothing was booked or charged. …"
}`;

const hace: [string, string][] = [
  ['Busca', 'Horarios y precios de cualquier ruta, de ida o de ida y vuelta, con adultos, jóvenes, mayores, niños y bebés. Paquetes Básica, Flexible y Superflexible, paradas intermedias y plazas para silla de ruedas.'],
  ['Elige', 'El asiento en el plano del autobús (ventanilla o pasillo), extras para todos o para un viajero: mascota, bici, seguro, el asiento de al lado. Descuentos de familia numerosa y de discapacidad.'],
  ['Paga', 'Con la tarjeta que ya tienes guardada en tu cuenta, con tus puntos (solos o con dinero), con el monedero, con una tarjeta nueva, PayPal, Bizum, Google Pay o Klarna. Sin <code>--yes</code> no compra nada: te enseña el desglose.'],
  ['Abono Único', 'Lo lee de tu cuenta y reserva los Comfort a 0 €. Te dice cuántos días le quedan y te cotiza el siguiente.'],
  ['Después', 'Tus viajes, cada billete con su asiento, su dársena y el estado del bus, el PDF, el QR de embarque y la anulación con el reembolso a la vista antes de confirmar.'],
  ['Para agentes', 'Todo sale en JSON, con códigos de salida claros. Un asistente de IA puede buscarte la guagua y dejártela lista para que la pagues tú.'],
];

const faq: [string, string][] = [
  ['¿Es oficial?', 'No. Habla con alsa.es igual que lo hace su propia web, sin acuerdo con ALSA. Si la web cambia, queguagua puede dejar de funcionar hasta que se arregle.'],
  ['¿Y mi contraseña?', 'Se queda en el llavero de tu Mac (o en variables de entorno). La CLI no la escribe en ningún fichero ni la manda a otro sitio que no sea ALSA.'],
  ['¿Puede comprar sin querer?', 'No. Sin <code>--yes</code> todo se queda en presupuesto. Los pagos con tarjeta los confirmas tú en la página del banco.'],
  ['¿Qué falta?', 'Cambiar un billete (anular, sí), la vuelta abierta (la propia web de ALSA no la vende ahora) y Apple Pay. Y las demás empresas: de momento, solo ALSA.'],
];

const html = `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>queguagua · ¿qué guagua cojo?</title>
<meta name="description" content="Las guaguas de España desde la terminal: horarios, precios, asientos, Abono Único y compra con tu propia cuenta. Empieza por ALSA.">
<meta name="theme-color" content="#faf7f0">
<meta property="og:title" content="queguagua · ¿qué guagua cojo?">
<meta property="og:description" content="Las guaguas de España desde la terminal. Empieza por ALSA.">
<link rel="icon" href="data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="3" y="6" width="26" height="18" rx="4" fill="none" stroke="#2433b5" stroke-width="2.4"/><path d="M6 11h20" stroke="#2433b5" stroke-width="2"/><circle cx="10" cy="25" r="3" fill="#faf7f0" stroke="#2433b5" stroke-width="2"/><circle cx="22" cy="25" r="3" fill="#faf7f0" stroke="#2433b5" stroke-width="2"/></svg>')}">
<script>try{if('IntersectionObserver'in window&&!matchMedia('(prefers-reduced-motion: reduce)').matches&&!/quieto/.test(location.search))document.documentElement.classList.add('anima')}catch(e){}</script>
<style>${css}</style>
</head>
<body>
<header class="cabecera">
  <a class="marca" href="/">queguagua</a>
  <span class="nota-cabecera">de momento, ALSA</span>
</header>

<main>
  <section class="portada">
    ${escena()}
    <div class="lema">
      <h1>¿Qué guagua cojo?</h1>
      <p class="entrada">Las guaguas de España desde la terminal. Busca horarios y precios, elige asiento, usa tu Abono Único y paga con la tarjeta que ya tienes guardada. Todo en JSON, para ti y para tu asistente de IA.</p>
      <div class="instalar">
        <pre><code id="orden">uv tool install 'queguagua[checkout] @ git+https://github.com/joseluissaorin/queguagua'</code></pre>
        <button type="button" class="copiar" data-copia="orden">Copiar</button>
      </div>
      <p class="aviso">Python 3.12 y <a href="https://docs.astral.sh/uv/">uv</a>. La orden es <code>queguagua</code>, o <code>qg</code> si tienes prisa.</p>
    </div>
  </section>

  <section class="bloque">
    <h2>Así se usa</h2>
    <p>Pregunta y te contesta. Esto es una búsqueda de verdad, con el Abono Único sacado de la cuenta:</p>
    <pre class="terminal"><code>${esc(busqueda)}</code></pre>
    <p>Y antes de comprar, siempre el presupuesto. Con <code>--yes</code> compra; si hay que pagar con tarjeta, te abre la página del banco para que lo confirmes tú.</p>
    <pre class="terminal"><code>${esc(compra)}</code></pre>
  </section>

  <section class="bloque">
    <h2>Qué hace</h2>
    <dl class="hace">
      ${hace.map(([t, d]) => `<div><dt>${t}</dt><dd>${d}</dd></div>`).join('\n      ')}
    </dl>
  </section>

  <section class="bloque">
    <h2>Empresas</h2>
    <ul class="empresas">
      <li><strong>ALSA</strong> <span>larga distancia, regionales y aeropuertos, en España, Portugal, Francia y Marruecos</span> <em>ya</em></li>
      <li class="pronto"><strong>Las siguientes guaguas</strong> <span>cada empresa entra como un grupo de órdenes nuevo, sin tocar las demás</span> <em>cuando toque</em></li>
    </ul>
  </section>

  <section class="bloque">
    <h2>Preguntas</h2>
    <dl class="faq">
      ${faq.map(([q, a]) => `<div><dt>${q}</dt><dd>${a}</dd></div>`).join('\n      ')}
    </dl>
  </section>
</main>

<footer class="pie">
  <p>queguagua no tiene relación con ALSA ni con ninguna empresa de transporte. <a href="https://github.com/joseluissaorin/queguagua">Código abierto</a>, licencia MIT.</p>
  <p>Dibujado a mano en Canarias por <a href="https://joseluissaorin.com">José Luis Saorín</a>.</p>
</footer>

<script>
(function(){
  var d=document.documentElement, e=document.querySelector('.escena');
  function ver(){ e.classList.add('visto'); [].forEach.call(e.querySelectorAll('svg.dibujo'),function(s){s.classList.add('visto')}); }
  if(!d.classList.contains('anima')) ver();
  else if('IntersectionObserver' in window){ var io=new IntersectionObserver(function(es){ if(es[0].isIntersecting){ ver(); io.disconnect(); } },{threshold:.2}); io.observe(e); }
  [].forEach.call(document.querySelectorAll('.copiar'),function(b){
    b.addEventListener('click',function(){
      var t=document.getElementById(b.getAttribute('data-copia')).textContent;
      (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){ b.textContent='Copiado'; setTimeout(function(){ b.textContent='Copiar'; },1600); },function(){ b.textContent='Selecciónalo'; });
    });
  });
  addEventListener('beforeprint', ver);
})();
</script>
</body>
</html>
`;

writeFileSync(dist + 'index.html', html);
console.log(`dist/index.html ${(html.length / 1024).toFixed(1)} KB`);
