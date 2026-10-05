function llenarDemo(idCampo, texto) {
    const campo = document.getElementById(idCampo);
    if (campo) {
        campo.value = texto;
        campo.focus();
    }
}

document.addEventListener('DOMContentLoaded', function () {
    const botones = document.querySelectorAll('[data-demo-campo]');
    botones.forEach(function (boton) {
        boton.addEventListener('click', function (evento) {
            evento.preventDefault();
            const campo = boton.getAttribute('data-demo-campo');
            const texto = boton.getAttribute('data-demo-texto');
            llenarDemo(campo, texto);
        });
    });
});
