"""Módulo para dibujar caricaturas ASCII en estilos humano, robot y gato."""

def dibujar_caricatura(estilo: str = 'humano', tamano: int = 1, nombre: str = '') -> str:
    """Dibuja una caricatura ASCII.

    El estilo 'humano' tiene exactamente 2 brazos dibujados una sola vez
    en la parte superior del torso. Los estilos 'robot' y 'gato' también
    tienen un único par de brazos (2 en total). Los tamaños 1, 2 y 3
    añaden más detalle y líneas al dibujo.
    """
    if estilo not in ('humano', 'robot', 'gato'):
        return f'Error: el estilo debe ser humano, robot o gato. Recibido: {estilo}'
    if tamano not in (1, 2, 3):
        return f'Error: el tamano debe ser 1, 2 o 3. Recibido: {tamano}'

    bs = chr(92)
    ap = chr(39)
    bt = chr(96)

    H = {
        1: ['   .--.', '  /o  o' + bs, '  ' + bs + ' -- /',
            '   ' + bt + '--' + ap, '   |||', '  -+-+-',
            '   |||', '   |||', '   /' + bs],
        2: ['   .--.', '  / o  o ' + bs, '  |  ..  |',
            '  ' + bs + ' -- /', '   ' + bt + '--' + ap,
            '   |||', '  -+-+-', '   ||||', '   ||||',
            '   ||||', '   /' + bs, '  /   ' + bs],
        3: ['    .--.', '   / o  o ' + bs, '   |  . . |',
            '   ' + bs + ' --- /', '    ' + bt + '---' + ap,
            '    ||||', '  -||||-', '    ||||', '    ||||',
            '    ||||', '    ||||', '    / ' + bs, '   /   ' + bs],
    }
    R = {
        1: ['  [-O-]', '  |[ ]|', '  |   |', '  [_|_]',
            '  /|' + bs, '   ||', '   ||', '  /' + bs + '='],
        2: ['   [-O-]', '   |[ ]|', '   | o |', '   [___]',
            '    |||', '   -+-+-', '    |||', '    |||',
            '    |||', '    /' + bs, '   /   ' + bs],
        3: ['    [-O-]', '    |[O]|', '    | . |', '    | o |',
            '    |[ ]|', '    [___]', '     |||', '   -||||-',
            '     ||||', '     ||||', '     ||||', '     ||||',
            '    /   ' + bs],
    }
    G = {
        1: ['  /' + bs + '  /' + bs, ' ( o.o )', '  > ^ <',
            ' /|   |' + bs, '  |   |', '  |   |', '  |   |',
            ' _/   ' + bs + '_'],
        2: ['   /' + bs + '  /' + bs, '  ( o.o )', '   > ^ <',
            '  /|   |' + bs, '   |   |', '   |   |',
            '   |   |', '   |   |', '  _/   ' + bs + '_'],
        3: ['    /' + bs + '  /' + bs, '   ( o.o )', '    > ^ <',
            '   /|   |' + bs, '    |   |', '    |   |',
            '    |   |', '    |   |', '    |   |',
            '    |   |', '   _/   ' + bs + '_'],
    }

    dibujo = chr(10).join({'humano': H, 'robot': R, 'gato': G}[estilo][tamano])
    if nombre:
        dibujo = '[' + nombre + ']' + chr(10) + dibujo
    return dibujo
