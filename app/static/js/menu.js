document.addEventListener('DOMContentLoaded', function () {
    const lateral = document.getElementById('menu-lateral');
    const boton = document.getElementById('menu-boton');
    if (!lateral || !boton) {
        return;
    }

    // Solo con JS el menú empieza cerrado; sin JS queda visible.
    lateral.classList.add('menu-js');

    function fijar(abierto) {
        lateral.classList.toggle('abierto', abierto);
        boton.setAttribute('aria-expanded', abierto ? 'true' : 'false');
        boton.setAttribute('aria-label', abierto ? 'Cerrar menú' : 'Abrir menú');
    }

    boton.addEventListener('click', function () {
        fijar(!lateral.classList.contains('abierto'));
    });

    // Tocar cualquier enlace del menú lo cierra.
    lateral.querySelectorAll('.lateral-cuerpo a').forEach(function (enlace) {
        enlace.addEventListener('click', function () {
            fijar(false);
        });
    });

    // Tocar fuera del menú lo cierra (si está abierto).
    document.addEventListener('click', function (evento) {
        if (lateral.classList.contains('abierto') && !lateral.contains(evento.target)) {
            fijar(false);
        }
    });

    document.addEventListener('keydown', function (evento) {
        if (evento.key === 'Escape') {
            fijar(false);
        }
    });
});
