import os
import sys
import unittest
from unittest import mock

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

# Base en memoria: no toca MySQL. Van antes de importar la app.
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SECRET_KEY'] = 'clave-solo-para-pruebas'

import requests

import bot
from app import create_app
from app.extensions import db
from app.models import AmenazaConfirmada, Usuario
from app.analysis.analyzer import INDICADOR_AMENAZA, analizar_mensaje
from app.analysis.forms import MAX_LARGO_MENSAJE


def falso_analizar(texto):
    return 'ANALIZADO'


class FormatearResultado(unittest.TestCase):
    def test_muestra_puntaje_nivel_y_solo_los_3_de_mas_peso(self):
        indicadores = [('a', 10, 'ea'), ('b', 40, 'eb'), ('c', 25, 'ec'), ('d', 30, 'ed'), ('e', 5, 'ee')]
        texto = bot.formatear_resultado(70, 'alto', indicadores)
        self.assertIn('70/100', texto)
        self.assertIn('ALTO', texto)
        self.assertIn('- b (+40): eb', texto)
        self.assertIn('- d (+30): ed', texto)
        self.assertIn('- c (+25): ec', texto)
        self.assertNotIn('(+10)', texto)
        self.assertNotIn('(+5)', texto)
        self.assertLess(texto.index('- b'), texto.index('- d'))
        self.assertLess(texto.index('- d'), texto.index('- c'))

    def test_alerta_si_hay_amenaza_confirmada(self):
        texto = bot.formatear_resultado(100, 'alto', [(INDICADOR_AMENAZA, 100, 'x'), ('b', 40, 'eb')])
        self.assertTrue(texto.startswith(bot.ALERTA_AMENAZA))
        self.assertIn('- b (+40): eb', texto)
        self.assertNotIn(f'- {INDICADOR_AMENAZA}', texto)  # la alerta no se repite como "señal"

    def test_alerta_sola_no_dice_que_no_hay_senales(self):
        texto = bot.formatear_resultado(100, 'alto', [(INDICADOR_AMENAZA, 100, 'x')])
        self.assertIn(bot.ALERTA_AMENAZA, texto)
        self.assertNotIn('No se detectaron', texto)

    def test_sin_indicadores(self):
        texto = bot.formatear_resultado(0, 'bajo', [])
        self.assertIn('0/100', texto)
        self.assertIn('No se detectaron señales', texto)
        self.assertNotIn('ALERTA', texto)

    def test_no_pasa_del_limite_de_telegram(self):
        texto = bot.formatear_resultado(50, 'medio', [('a', 5, 'x' * 10000)])
        self.assertLessEqual(len(texto), bot.MAX_LARGO_RESPUESTA)


MENSAJE_NEQUI = ('Felicidades! Ganaste un bono de $500.000 de Nequi. Reclamalo antes de 24 horas: '
                 'http://nequl.com.co/premio y confirma en bit.ly/bono-nequi')


class Neutralizar(unittest.TestCase):
    def test_enlaces_menciones_y_comandos_copiados(self):
        self.assertEqual(bot.neutralizar('ver http://nequl.com.co/premio'), 'ver hxxp://nequl[.]com[.]co/premio')
        self.assertEqual(bot.neutralizar('HTTPS://Sitio.com'), 'hxxpS://Sitio[.]com')  # conserva el caso de la "s"; igual no es tocable
        self.assertEqual(bot.neutralizar('www.sitio.com y bit.ly/abc'), 'www[.]sitio[.]com y bit[.]ly/abc')
        self.assertEqual(bot.neutralizar('escribe a @admin o a juan@mail.com'), 'escribe a [@]admin o a juan[@]mail[.]com')
        self.assertEqual(bot.neutralizar('/start y /ayuda'), '[/]start y [/]ayuda')

    def test_no_toca_la_prosa_normal(self):
        for texto in ('Detectado: 24 horas.', 'Fin de frase. Otra frase.', 'puntaje 35).', 'a/b'):
            with self.subTest(texto=texto):
                self.assertEqual(bot.neutralizar(texto), texto)

    def test_la_ruta_de_un_enlace_no_se_confunde_con_un_comando(self):
        self.assertIn('/premio', bot.neutralizar('nequl.com.co/premio'))
        self.assertNotIn('[/]premio', bot.neutralizar('nequl.com.co/premio'))

    def test_respuesta_al_mensaje_de_nequi_sin_nada_tocable(self):
        puntaje, nivel, indicadores = analizar_mensaje(MENSAJE_NEQUI, {})
        respuesta = bot.formatear_resultado(puntaje, nivel, indicadores)
        self.assertIn('hxxp://nequl[.]com[.]co/premio', respuesta)  # el enlace se ve, pero inofensivo
        self.assertNotIn('http://', respuesta)
        self.assertNotIn('https://', respuesta)
        self.assertNotIn('nequl.com.co', respuesta)
        self.assertNotIn('bit.ly', respuesta)
        self.assertNotIn('@', respuesta)

    def test_el_texto_fijo_del_bot_no_se_neutraliza(self):
        self.assertEqual(bot.armar_respuesta({'text': '/start'}, falso_analizar), bot.TEXTO_AYUDA)
        self.assertIn('/start y /ayuda', bot.TEXTO_AYUDA)
        texto = bot.formatear_resultado(100, 'alto', [(INDICADOR_AMENAZA, 100, 'x')])
        self.assertTrue(texto.startswith(bot.ALERTA_AMENAZA))


class ArmarRespuesta(unittest.TestCase):
    def test_mensajes_que_no_son_texto(self):
        for mensaje in ({'photo': [{}]}, {'sticker': {}}, {'voice': {}}, {'document': {}}, {'text': None}, {'text': '   '}):
            with self.subTest(mensaje=mensaje):
                analizar = mock.Mock()
                self.assertEqual(bot.armar_respuesta(mensaje, analizar), bot.TEXTO_NO_TEXTO)
                analizar.assert_not_called()

    def test_comandos_de_ayuda(self):
        for texto in ('/start', '/ayuda', '/START', '/start@phishguard_ucc_bot', '/ayuda algo'):
            with self.subTest(texto=texto):
                analizar = mock.Mock()
                self.assertEqual(bot.armar_respuesta({'text': texto}, analizar), bot.TEXTO_AYUDA)
                analizar.assert_not_called()

    def test_comando_desconocido_no_se_analiza(self):
        analizar = mock.Mock()
        self.assertEqual(bot.armar_respuesta({'text': '/otro'}, analizar), bot.TEXTO_COMANDO_DESCONOCIDO)
        analizar.assert_not_called()

    def test_texto_normal_se_analiza(self):
        analizar = mock.Mock(return_value='RESPUESTA')
        self.assertEqual(bot.armar_respuesta({'text': '  hola  '}, analizar), 'RESPUESTA')
        analizar.assert_called_once_with('hola')

    def test_limite_de_largo_igual_que_la_web(self):
        analizar = mock.Mock(return_value='ok')
        self.assertEqual(bot.armar_respuesta({'text': 'a' * MAX_LARGO_MENSAJE}, analizar), 'ok')
        self.assertEqual(bot.armar_respuesta({'text': 'a' * (MAX_LARGO_MENSAJE + 1)}, analizar), bot.TEXTO_MUY_LARGO)
        self.assertEqual(analizar.call_count, 1)

    def test_si_falla_el_analisis_responde_generico_y_no_filtra_el_error(self):
        def falla(texto):
            raise RuntimeError('mysql://usuario:clave@host/db')
        with mock.patch('sys.stderr'):
            self.assertEqual(bot.armar_respuesta({'text': 'hola'}, falla), bot.TEXTO_ERROR)

    def test_no_imprime_el_contenido(self):
        with mock.patch('builtins.print') as imprimir:
            bot.armar_respuesta({'text': 'SECRETO-DEL-USUARIO'}, falso_analizar)
        self.assertEqual(imprimir.call_count, 0)


class AnalizarTextoConMotor(unittest.TestCase):
    """Usa el motor real con SQLite en memoria: pesos de la BD, amenazas y un contexto por mensaje."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        with cls.app.app_context():
            db.create_all()
            admin = Usuario(username='root', email='root@ejemplo.co', password_hash='x', es_admin=True)
            db.session.add(admin)
            db.session.commit()
            cls.admin_id = admin.id

    def test_usa_amenazas_nuevas_sin_reiniciar(self):
        texto = 'Mira esto http://sitio-malo-prueba.xyz/login'
        antes = bot.analizar_texto(self.app, texto)
        self.assertNotIn(bot.ALERTA_AMENAZA, antes)
        with self.app.app_context():
            db.session.add(AmenazaConfirmada(dominio='sitio-malo-prueba.xyz', confirmado_por_id=self.admin_id))
            db.session.commit()
        despues = bot.analizar_texto(self.app, texto)
        self.assertIn(bot.ALERTA_AMENAZA, despues)
        self.assertIn('100/100', despues)

    def test_no_guarda_nada(self):
        from app.models import Analisis, EventoSeguridad
        bot.analizar_texto(self.app, 'Urgente: verifica tu cuenta en http://banco-falso.xyz')
        with self.app.app_context():
            self.assertEqual(Analisis.query.count(), 0)
            self.assertEqual(EventoSeguridad.query.count(), 0)


class CapaDeRed(unittest.TestCase):
    def test_enviar_es_texto_plano_sin_parse_mode(self):
        with mock.patch('requests.Session.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'ok': True, 'result': {}}
            bot.Telegram('TOKEN-SECRETO').enviar(123, '<b>hola</b>')
        carga = post.call_args.kwargs['json']
        self.assertNotIn('parse_mode', carga)
        self.assertEqual(carga['text'], '<b>hola</b>')
        self.assertIsNotNone(post.call_args.kwargs['timeout'])

    def test_error_de_red_no_filtra_el_token(self):
        error = requests.ConnectionError('HTTPSConnectionPool: /botTOKEN-SECRETO/getUpdates')
        with mock.patch('requests.Session.post', side_effect=error):
            with self.assertRaises(bot.ErrorTelegram) as ctx:
                bot.Telegram('TOKEN-SECRETO').obtener_updates(None)
        self.assertNotIn('TOKEN-SECRETO', str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)

    def test_json_que_no_es_un_objeto_es_error_controlado(self):
        for cuerpo in ([], [1, 2], 5, 'texto', None):
            with self.subTest(cuerpo=cuerpo):
                with mock.patch('requests.Session.post') as post:
                    post.return_value.status_code = 200
                    post.return_value.json.return_value = cuerpo
                    with self.assertRaises(bot.ErrorTelegram):
                        bot.Telegram('x').obtener_updates(None)

    def test_el_bucle_sigue_vivo_con_una_respuesta_anomala(self):
        with mock.patch('requests.Session.post') as post, mock.patch('time.sleep') as dormir, mock.patch('sys.stderr'):
            post.return_value.status_code = 200
            post.return_value.json.side_effect = [[], KeyboardInterrupt()]
            with self.assertRaises(KeyboardInterrupt):
                bot.ejecutar(bot.Telegram('x'), falso_analizar)
        dormir.assert_called_once_with(bot.ESPERA_MIN)  # reintentó con espera en lugar de morir

    def test_ok_sin_result_es_error_controlado(self):
        with mock.patch('requests.Session.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'ok': True}
            with self.assertRaises(bot.ErrorTelegram):
                bot.Telegram('x').enviar(1, 'hola')

    def test_getupdates_con_result_que_no_es_lista_es_error_controlado(self):
        with mock.patch('requests.Session.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'ok': True, 'result': {'a': 1}}
            with self.assertRaises(bot.ErrorTelegram):
                bot.Telegram('x').obtener_updates(None)

    def test_no_sigue_redirecciones(self):
        with mock.patch('requests.Session.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'ok': True, 'result': []}
            bot.Telegram('x').obtener_updates(None)
        self.assertIs(post.call_args.kwargs['allow_redirects'], False)

    def test_una_redireccion_es_error_controlado_sin_filtrar_el_token(self):
        with mock.patch('requests.Session.post') as post:
            post.return_value.status_code = 301
            post.return_value.json.side_effect = ValueError('sin cuerpo')
            with self.assertRaises(bot.ErrorTelegram) as ctx:
                bot.Telegram('TOKEN-SECRETO').obtener_updates(None)
        self.assertNotIn('TOKEN-SECRETO', str(ctx.exception))

    def test_elementos_anomalos_en_el_lote_no_matan_el_bucle(self):
        telegram = mock.Mock()
        valido = {'update_id': 3, 'message': {'chat': {'id': 1}, 'photo': [{}]}}
        telegram.obtener_updates.side_effect = [['basura', 5, None, {'sin': 'id'}, {'update_id': 'x'}, valido],
                                                KeyboardInterrupt()]
        with mock.patch('time.sleep') as dormir, mock.patch('sys.stderr'):
            with self.assertRaises(KeyboardInterrupt):
                bot.ejecutar(telegram, falso_analizar)
        dormir.assert_not_called()
        self.assertEqual(telegram.obtener_updates.call_args_list[-1].args, (4,))
        telegram.enviar.assert_called_once_with(1, bot.TEXTO_NO_TEXTO)

    def test_lote_solo_anomalo_espera_en_vez_de_repetir_sin_pausa(self):
        telegram = mock.Mock()
        telegram.obtener_updates.side_effect = [['basura', 7], KeyboardInterrupt()]
        with mock.patch('time.sleep') as dormir, mock.patch('sys.stderr'):
            with self.assertRaises(KeyboardInterrupt):
                bot.ejecutar(telegram, falso_analizar)
        dormir.assert_called_once_with(bot.ESPERA_MIN)
        telegram.enviar.assert_not_called()

    def test_401_es_token_invalido(self):
        with mock.patch('requests.Session.post') as post:
            post.return_value.status_code = 401
            with self.assertRaises(bot.TokenInvalido):
                bot.Telegram('x').obtener_updates(None)

    def test_offset_avanza_y_se_reintenta_con_espera(self):
        telegram = mock.Mock()
        telegram.obtener_updates.side_effect = [
            bot.ErrorTelegram('caída'),
            [{'update_id': 7, 'message': {'chat': {'id': 1}, 'photo': [{}]}}],
            KeyboardInterrupt(),
        ]
        with mock.patch('time.sleep') as dormir, mock.patch('sys.stderr'):
            with self.assertRaises(KeyboardInterrupt):
                bot.ejecutar(telegram, falso_analizar)
        dormir.assert_called_once_with(bot.ESPERA_MIN)
        self.assertEqual(telegram.obtener_updates.call_args_list[-1].args, (8,))
        telegram.enviar.assert_called_once_with(1, bot.TEXTO_NO_TEXTO)

    def test_la_espera_crece_y_tiene_tope(self):
        telegram = mock.Mock()
        telegram.obtener_updates.side_effect = [bot.ErrorTelegram('x')] * 8 + [KeyboardInterrupt()]
        with mock.patch('time.sleep') as dormir, mock.patch('sys.stderr'):
            with self.assertRaises(KeyboardInterrupt):
                bot.ejecutar(telegram, falso_analizar)
        esperas = [c.args[0] for c in dormir.call_args_list]
        self.assertEqual(esperas, [2, 4, 8, 16, 32, 60, 60, 60])


class ConexionAMysql(unittest.TestCase):
    def test_el_pool_prueba_y_renueva_las_conexiones(self):
        opciones = create_app().config['SQLALCHEMY_ENGINE_OPTIONS']
        self.assertIs(opciones['pool_pre_ping'], True)
        self.assertLessEqual(opciones['pool_recycle'], 300)  # menos que el wait_timeout típico de un hosting

    def test_cada_mensaje_abre_y_cierra_su_contexto_y_su_sesion(self):
        app = create_app()
        with app.app_context():
            db.create_all()
        with mock.patch.object(db.session, 'remove', wraps=db.session.remove) as remove:
            bot.analizar_texto(app, 'hola')
            bot.analizar_texto(app, 'hola otra vez')
        self.assertEqual(remove.call_count, 2)  # la sesión se cierra al salir de cada contexto


class LimitePorChat(unittest.TestCase):
    def setUp(self):
        self.ahora = [100.0]
        self.limite = bot.LimitePorChat(maximo=3, ventana=60, reloj=lambda: self.ahora[0])

    def test_permite_hasta_el_maximo_avisa_una_vez_e_ignora_el_resto(self):
        estados = [self.limite.revisar(1) for _ in range(7)]
        self.assertEqual(estados, ['permitido'] * 3 + ['aviso'] + ['ignorado'] * 3)

    def test_cada_chat_tiene_su_propio_contador(self):
        for _ in range(3):
            self.limite.revisar(1)
        self.assertEqual(self.limite.revisar(1), 'aviso')
        self.assertEqual(self.limite.revisar(2), 'permitido')

    def test_se_libera_al_pasar_la_ventana_y_puede_avisar_de_nuevo(self):
        for _ in range(4):
            self.limite.revisar(1)
        self.ahora[0] += 61
        self.assertEqual([self.limite.revisar(1) for _ in range(4)], ['permitido'] * 3 + ['aviso'])

    def test_la_memoria_tiene_tope(self):
        for chat in range(bot.MAX_CHATS_EN_MEMORIA):
            self.limite.revisar(chat)
        self.ahora[0] += 61
        self.limite.revisar('nuevo')  # al llegar al tope se limpian los chats vencidos
        self.assertEqual(len(self.limite._chats), 1)

    def test_con_todos_los_chats_activos_la_tabla_no_pasa_del_tope(self):
        # Ningún chat está vencido (todos escribieron hace 1 s): la limpieza no libera nada y hay que expulsar uno.
        for chat in range(bot.MAX_CHATS_EN_MEMORIA):
            self.ahora[0] += 0.001
            self.limite.revisar(chat)
        for extra in range(50):
            self.ahora[0] += 0.001
            self.assertEqual(self.limite.revisar(f'nuevo{extra}'), 'permitido')
            self.assertLessEqual(len(self.limite._chats), bot.MAX_CHATS_EN_MEMORIA)
        self.assertNotIn(0, self.limite._chats)  # salió el más antiguo
        self.assertIn('nuevo49', self.limite._chats)

    def test_un_chat_ya_conocido_no_expulsa_a_otros_al_estar_lleno(self):
        for chat in range(bot.MAX_CHATS_EN_MEMORIA):
            self.ahora[0] += 0.001
            self.limite.revisar(chat)
        self.limite.revisar(500)
        self.assertEqual(len(self.limite._chats), bot.MAX_CHATS_EN_MEMORIA)
        self.assertIn(0, self.limite._chats)

    def test_procesar_update_responde_espera_una_vez_y_no_analiza(self):
        telegram = mock.Mock()
        analizar = mock.Mock(return_value='ok')
        update = {'update_id': 1, 'message': {'chat': {'id': 5}, 'text': 'hola'}}
        for _ in range(6):
            bot.procesar_update(update, telegram, analizar, self.limite)
        enviados = [c.args[1] for c in telegram.enviar.call_args_list]
        self.assertEqual(enviados, ['ok'] * 3 + [bot.TEXTO_ESPERA])
        self.assertEqual(analizar.call_count, 3)

    def test_el_limite_aplica_tambien_a_mensajes_que_no_son_texto(self):
        telegram = mock.Mock()
        update = {'update_id': 1, 'message': {'chat': {'id': 5}, 'sticker': {}}}
        for _ in range(5):
            bot.procesar_update(update, telegram, falso_analizar, self.limite)
        enviados = [c.args[1] for c in telegram.enviar.call_args_list]
        self.assertEqual(enviados, [bot.TEXTO_NO_TEXTO] * 3 + [bot.TEXTO_ESPERA])


if __name__ == '__main__':
    unittest.main()
