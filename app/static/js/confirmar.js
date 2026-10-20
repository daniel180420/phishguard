// Pide confirmación antes de enviar los formularios marcados con data-confirmar="mensaje".
// Se usa para los borrados: si la persona cancela, el formulario no se envía.
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-confirmar]').forEach(function (formulario) {
        formulario.addEventListener('submit', function (evento) {
            if (!window.confirm(formulario.getAttribute('data-confirmar'))) {
                evento.preventDefault();
            }
        });
    });
});
