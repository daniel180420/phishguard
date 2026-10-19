// Lectura de códigos QR en el navegador. La imagen nunca se envía al servidor:
// se decodifica aquí con jsQR y solo se usa el texto que contiene.

const QR_MAX_BYTES = 10 * 1024 * 1024;   // 10 MB
const QR_LADO_MAX = 1280;                // px; las fotos más grandes se reducen antes de leerlas
const URL_MAX_LARGO = 500;               // el mismo límite que valida el servidor
const TEXTO_MAX_MOSTRADO = 300;

// Texto del último QR que se puso en el campo: sirve para saber si el usuario lo cambió después.
let urlDelQr = '';

function mostrarEstado(mensaje, tipo, contenido) {
    const estado = document.getElementById('qr-estado');
    const texto = document.getElementById('qr-texto');
    // textContent siempre: lo que trae el QR lo controla quien lo hizo, nunca se interpreta como HTML.
    estado.textContent = mensaje;
    estado.className = 'qr-estado qr-' + tipo;
    estado.hidden = false;
    if (contenido) {
        texto.textContent = contenido.length > TEXTO_MAX_MOSTRADO
            ? contenido.slice(0, TEXTO_MAX_MOSTRADO) + '…'
            : contenido;
        texto.hidden = false;
    } else {
        texto.textContent = '';
        texto.hidden = true;
    }
}

function clasificarContenido(texto) {
    // Devuelve { url } si es un enlace web que se puede poner en el campo, o { error } si no.
    if (/\s/.test(texto)) {
        return { error: 'El QR contiene texto, no un enlace web.' };
    }
    if (/^https?:\/\//i.test(texto)) {
        return { url: texto, agregoEsquema: false };
    }
    if (/^www\./i.test(texto)) {
        return { url: 'http://' + texto, agregoEsquema: true };
    }
    if (/^[a-z][a-z0-9+.\-]*:/i.test(texto)) {
        return { error: 'El QR no contiene un enlace web (http o https), así que no se puso en el campo. No lo abras.' };
    }
    return { error: 'El QR contiene texto, no un enlace web.' };
}

function fallarLectura(mensaje) {
    // La imagen no se pudo leer: el enlace de un QR anterior ya no corresponde a lo que el usuario eligió.
    olvidarQrAnterior(document.getElementById('url'));
    mostrarEstado(mensaje, 'error');
}

async function leerQr(archivo) {
    if (archivo.size > QR_MAX_BYTES) {
        fallarLectura('La imagen pesa más de 10 MB. Elige una más pequeña.');
        return;
    }
    if (typeof createImageBitmap !== 'function' || typeof jsQR !== 'function') {
        mostrarEstado('Este navegador no puede leer QR desde una imagen. Escribe o pega la dirección.', 'error');
        return;
    }

    let imagen;
    try {
        // createImageBitmap no necesita una URL blob: ni data:, que la CSP bloquea.
        imagen = await createImageBitmap(archivo);
    } catch (e) {
        fallarLectura('No se pudo abrir la imagen. Prueba con otra foto (JPG o PNG).');
        return;
    }

    try {
        const escala = Math.min(1, QR_LADO_MAX / Math.max(imagen.width, imagen.height));
        const ancho = Math.max(1, Math.round(imagen.width * escala));
        const alto = Math.max(1, Math.round(imagen.height * escala));
        const lienzo = document.createElement('canvas');
        lienzo.width = ancho;
        lienzo.height = alto;
        const ctx = lienzo.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(imagen, 0, 0, ancho, alto);
        const pixeles = ctx.getImageData(0, 0, ancho, alto);
        const codigo = jsQR(pixeles.data, ancho, alto, { inversionAttempts: 'attemptBoth' });

        if (!codigo || !codigo.data) {
            fallarLectura('No se encontró ningún código QR legible. Acércate, enfoca y evita reflejos.');
            return;
        }
        mostrarResultado(codigo.data.trim());
    } catch (e) {
        fallarLectura('No se pudo leer la imagen. Prueba con otra foto.');
    } finally {
        imagen.close();
    }
}

function olvidarQrAnterior(campo) {
    // Si el campo aún tiene el enlace de un QR anterior, se vacía: ya no corresponde a lo que se leyó
    // y el usuario podría analizarlo creyendo que es el del QR nuevo. Si el usuario escribió o editó
    // otra cosa, no se toca.
    if (urlDelQr && campo.value.trim() === urlDelQr) {
        campo.value = '';
    }
    urlDelQr = '';
}

function mostrarResultado(texto) {
    const campo = document.getElementById('url');
    const clasificado = clasificarContenido(texto);

    if (clasificado.error) {
        olvidarQrAnterior(campo);
        mostrarEstado(clasificado.error, 'aviso', texto);
        return;
    }
    if (clasificado.url.length > URL_MAX_LARGO) {
        olvidarQrAnterior(campo);
        mostrarEstado('El enlace del QR tiene más de 500 caracteres, no se puso en el campo.', 'aviso', texto);
        return;
    }

    campo.value = clasificado.url;
    // Avisa a quien escuche el campo (autocompletado, extensiones del navegador).
    campo.dispatchEvent(new Event('input', { bubbles: true }));
    if (campo.value !== clasificado.url) {
        // No se dice "el QR contiene este enlace" si el campo no quedó con él.
        urlDelQr = '';
        mostrarEstado('No se pudo escribir la dirección en el campo. Cópiala del texto de abajo y pégala.', 'error', clasificado.url);
        return;
    }
    urlDelQr = clasificado.url;
    // Si algo vacía el campo un instante después (autocompletado, extensión), se escribe de nuevo.
    setTimeout(function () {
        if (campo.value === '' && urlDelQr === clasificado.url) {
            console.warn('El campo URL se vació después de leer el QR; se vuelve a escribir.');
            campo.value = clasificado.url;
        }
    }, 500);
    if (clasificado.agregoEsquema) {
        mostrarEstado('El QR no traía http://, se agregó para analizarlo. Revisa la dirección antes de analizar.', 'aviso', clasificado.url);
    } else {
        mostrarEstado('El QR contiene este enlace. Revísalo antes de analizar.', 'ok', clasificado.url);
    }
}

document.addEventListener('DOMContentLoaded', function () {
    const boton = document.getElementById('qr-boton');
    const entrada = document.getElementById('qr-archivo');
    const formulario = document.getElementById('url').form;
    if (!boton || !entrada || !formulario) {
        return;
    }

    boton.addEventListener('click', function () {
        entrada.click();
    });

    entrada.addEventListener('change', function () {
        const archivo = entrada.files && entrada.files[0];
        if (archivo) {
            leerQr(archivo);
        }
        // Se vacía para poder elegir la misma foto otra vez.
        entrada.value = '';
    });

    // Al enviar, se marca el origen solo si el campo sigue siendo exactamente el enlace del QR.
    // El servidor vuelve a validar el valor (solo acepta "qr").
    formulario.addEventListener('submit', function () {
        const origen = document.getElementById('origen');
        const campo = document.getElementById('url');
        if (origen) {
            origen.value = (urlDelQr && campo.value.trim() === urlDelQr) ? 'qr' : '';
        }
    });
});
