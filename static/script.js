// Script para validação e suporte a barcode scanner
document.addEventListener('DOMContentLoaded', () => {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', (e) => {
            const inputs = form.querySelectorAll('input[required]');
            let valid = true;
            inputs.forEach(input => {
                if (!input.value) {
                    valid = false;
                    input.setAttribute('aria-invalid', 'true');
                    alert('Campo obrigatório: ' + input.name);
                }
            });
            if (!valid) e.preventDefault();
        });
    });
    // Navegação por teclado
    document.querySelectorAll('a, button, input').forEach(el => {
        el.addEventListener('focus', () => el.style.outline = '2px solid blue');
        el.addEventListener('blur', () => el.style.outline = 'none');
    });

    // Suporte a Barcode Scanner: Detecta sequências rápidas de teclas
    let barcode = '';
    let lastKeyTime = Date.now();
    document.addEventListener('keydown', (e) => {
        const currentTime = Date.now();
        if (currentTime - lastKeyTime > 50) { // Reset se >50ms entre teclas (não é scan)
            barcode = '';
        }
        lastKeyTime = currentTime;
        if (e.key !== 'Enter') {
            barcode += e.key;
        } else if (barcode.length > 0) {
            // Scan detectado: Preenche o campo codigo_barras se existir
            const input = document.getElementById('codigo_barras');
            if (input) {
                input.value = barcode;
                input.dispatchEvent(new Event('input')); // Trigger event
            }
            barcode = '';
        }
    });
});