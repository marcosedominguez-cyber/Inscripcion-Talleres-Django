import { useCallback, useEffect, useState } from 'react';
import { api } from './cuentas/api.js';
import InstructorPanel from './gestion/InstructorPanel.jsx';
import CatalogoParticipante from './participantes/CatalogoParticipante.jsx';

export default function App() {
  const [pantalla, setPantalla] = useState('inicio');
  const [rol, setRol] = useState('participante');
  const [usuario, setUsuario] = useState(null);
  const [iniciando, setIniciando] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');
  const [mensaje, setMensaje] = useState('');

  const sesionCaducada = useCallback(() => {
    setUsuario(null);
    setPantalla('login');
    setError('Tu sesión finalizó. Inicia sesión nuevamente.');
    setMensaje('');
  }, []);

  useEffect(() => {
    let activo = true;
    api('sesion').then(({ usuario }) => {
      if (activo && usuario) {
        setUsuario(usuario);
        setPantalla(usuario.rol === 'participante' ? 'catalogo' : 'cuenta');
      }
    }).catch((e) => { if (activo) setError(e.message); })
      .finally(() => { if (activo) setIniciando(false); });
    return () => { activo = false; };
  }, []);

  function navegar(destino, tipo = 'participante') {
    setPantalla(destino);
    setRol(tipo);
    setError('');
    setMensaje('');
  }

  async function enviar(event) {
    event.preventDefault();
    if (enviando || iniciando) return;
    const datos = Object.fromEntries(new FormData(event.currentTarget));
    setError('');
    setMensaje('');
    if (pantalla === 'registro' && datos.contrasena !== datos.confirmar_contrasena) {
      setError('Las contraseñas no coinciden.');
      return;
    }
    setEnviando(true);
    try {
      // Refrescar CSRF antes de cada operación también permite recuperarse de una sesión caducada.
      await api('sesion');
      if (pantalla === 'registro') {
        const result = await api('registro', { ...datos, rol });
        setPantalla('login');
        setMensaje(result.mensaje);
      } else {
        const result = await api('login', { ...datos, rol });
        setUsuario(result.usuario);
        setPantalla(result.usuario.rol === 'participante' ? 'catalogo' : 'cuenta');
      }
    } catch (e) {
      setError(e instanceof TypeError ? 'No se pudo conectar con el servidor.' : e.message);
    } finally {
      setEnviando(false);
    }
  }

  async function cerrarSesion() {
    setEnviando(true);
    setError('');
    try {
      await api('sesion');
      await api('logout', {});
      setUsuario(null);
      navegar('inicio');
    } catch (e) { setError(e.message); }
    finally { setEnviando(false); }
  }

  if (!iniciando && pantalla === 'catalogo' && usuario?.rol === 'participante') {
    return <CatalogoParticipante usuario={usuario} onCerrarSesion={cerrarSesion}
      onSesionCaducada={sesionCaducada} enviando={enviando} error={error} />;
  }

  if (!iniciando && usuario?.rol === 'instructor') {
    return <InstructorPanel usuario={usuario} onCerrarSesion={cerrarSesion}
      onSesionCaducada={sesionCaducada} />;
  }

  const acceso = pantalla === 'login' || pantalla === 'registro';
  return (
    <div className="jw-site">
      <a className="jw-skip" href="#contenido">Ir al contenido</a>
      <header className="jw-header">
        <button className="jw-brand" onClick={() => navegar('inicio')} aria-label="join.a.workshop, inicio">
          <svg className="jw-join-logo" viewBox="0 0 66 52" fill="none" aria-hidden="true" focusable="false"><path d="M28.26 43.21A18 18 0 1 1 36.79 37.57" stroke="#193c38" strokeWidth="8" /><path d="M37.74 8.79A18 18 0 1 1 29.21 14.43" stroke="#176456" strokeWidth="8" /></svg>join.a.workshop<span className="jw-dot">.</span>
        </button>
        <nav aria-label="Navegación principal">
          <a href="#como-funciona" onClick={() => navegar('inicio')}>Cómo funciona</a>
          <button className="jw-nav-login" onClick={() => navegar('login')}>Iniciar sesión <span aria-hidden="true">↗</span></button>
        </nav>
      </header>
      <main id="contenido">
        {iniciando && <p className="jw-notice" role="status">Comprobando sesión…</p>}
        {error && <p className="jw-notice jw-error" role="alert">{error}</p>}
        {mensaje && <p className="jw-notice" role="status">{mensaje}</p>}
        {!iniciando && pantalla === 'inicio' && <>
          <section className="jw-hero" aria-labelledby="home-title">
            <div className="jw-hero-copy">
              <p className="jw-eyebrow"><span /> PARA MENTES QUE NO SE QUEDAN QUIETAS</p>
              <h1 id="home-title">Una nueva idea.<br />Un nuevo comienzo.<br /><em>Un taller para ti.</em></h1>
              <p className="jw-lead">Hay cosas que se aprenden haciendo. Encuentra tu próximo taller, comparte lo que sabes y dale espacio a tu curiosidad.</p>
              <div className="jw-actions">
                <button className="jw-button" onClick={() => navegar('login')}>Descubrir talleres <span aria-hidden="true">↗</span></button>
                <button className="jw-text-button" onClick={() => navegar('registro', 'instructor')}>Quiero enseñar <span aria-hidden="true">→</span></button>
              </div>
              <div className="jw-hero-foot"><span className="jw-mini-spark" aria-hidden="true"><span className="jw-join-mark" aria-hidden="true" /></span><p>Aprende algo nuevo.<br /><strong>Hazlo parte de ti.</strong></p></div>
            </div>
            <div className="jw-art" aria-label="Ilustración de tarjetas de aprendizaje">
              <div className="jw-art-orbit" /><span className="jw-art-note">MENOS RUTINA. MÁS CURIOSIDAD.</span>
              <div className="jw-paper jw-paper-back"><span>UNA IDEA PUEDE</span><strong>cambiar<br />tu día.</strong><span className="jw-paper-sun" aria-hidden="true"><span className="jw-join-mark" aria-hidden="true" /></span></div>
              <div className="jw-paper jw-paper-front"><span>TU PRÓXIMO PASO</span><div className="jw-paper-drawing" aria-hidden="true"><i /><i /><i /></div><strong>empieza<br />por aquí<span>.</span></strong><div className="jw-paper-bottom">join.a.workshop <span>↗</span></div></div>
              <span className="jw-art-spark" aria-hidden="true"><span className="jw-join-mark" aria-hidden="true" /></span><span className="jw-art-caption">El gusto de empezar algo.</span>
            </div>
          </section>
          <div className="jw-ribbon"><span>Aprender haciendo</span><i><span className="jw-join-mark" aria-hidden="true" /></i><span>Compartir ideas</span><i><span className="jw-join-mark" aria-hidden="true" /></i><span>Encontrar tu espacio</span><i><span className="jw-join-mark" aria-hidden="true" /></i><span>Volver a sorprenderte</span></div>
          <section id="como-funciona" className="jw-how">
            <div className="jw-section-heading"><div><p className="jw-eyebrow">ASÍ DE SIMPLE</p><h2>De la curiosidad<br />a la acción.</h2></div><p>Tu próxima experiencia empieza con un pequeño paso. Tú eliges cuál.</p></div>
            <div className="jw-steps">
              <article><span className="jw-step-number">01 /</span><span className="jw-step-icon" aria-hidden="true">⌕</span><h3>Encuentra tu taller</h3><p>Explora las propuestas y encuentra ese tema que te da ganas de saber más.</p></article>
              <article><span className="jw-step-number">02 /</span><span className="jw-step-icon" aria-hidden="true">↗</span><h3>Hazte un lugar</h3><p>Inscríbete desde tu cuenta. Si el taller está lleno, consulta su lista de espera.</p></article>
              <article><span className="jw-step-number">03 /</span><span className="jw-step-icon" aria-hidden="true"><span className="jw-join-mark" aria-hidden="true" /></span><h3>Empieza algo nuevo</h3><p>Guarda la fecha y prepárate para aprender, practicar y compartir.</p></article>
            </div>
          </section>
          <section className="jw-teach"><div><p className="jw-eyebrow">DEL OTRO LADO DE LA MESA</p><h2>Eso que sabes,<br /><em>alguien quiere aprenderlo.</em></h2><p>Crea tu cuenta de instructor y propón tu próximo taller.</p></div><button className="jw-button jw-button-light" onClick={() => navegar('registro', 'instructor')}>¿Quieres publicar talleres? <span aria-hidden="true">↗</span></button></section>
        </>}
        {!iniciando && acceso && <div className="jw-access-layout">
          <aside className="jw-access-story"><p className="jw-eyebrow">UN ESPACIO PARA LO QUE VIENE</p><h2>{rol === 'instructor' ? <>Tu conocimiento.<br /> Su próximo<br /> <em>descubrimiento.</em></> : <>Qué bueno<br /> que sigas<br /> <em>explorando.</em></>}</h2><p>{rol === 'instructor' ? 'Comparte lo que te apasiona. Tu próximo taller puede ser el comienzo de algo para alguien más.' : 'Vuelve a tus ideas pendientes. Hay algo nuevo esperando a que le hagas un lugar.'}</p><div className="jw-access-art" aria-hidden="true"><span><span className="jw-join-mark" aria-hidden="true" /></span><div>nunca dejes<br /><strong>de aprender.</strong></div></div><span className="jw-story-foot">join.a.workshop · El gusto de aprender.</span></aside>
          <section className="jw-form-panel acceso">
            <button className="jw-back" onClick={() => navegar('inicio')}>← Volver al inicio</button>
            <p className="jw-eyebrow">{pantalla === 'login' ? 'BIENVENIDO DE NUEVO' : 'EMPIEZA POR AQUÍ'}</p>
            <h1>{pantalla === 'login' ? 'Iniciar sesión' : `Registro de ${rol}`}</h1>
            <p className="jw-form-intro">{pantalla === 'login' ? 'Entra a tu espacio y sigue donde lo dejaste.' : 'Unos pocos datos y un mundo por descubrir.'}</p>
            <div className="jw-role-picker" role="group" aria-label="Tipo de cuenta">
              <button type="button" aria-pressed={rol === 'participante'} disabled={enviando} onClick={() => navegar(pantalla, 'participante')}>Participante</button>
              <button type="button" aria-pressed={rol === 'instructor'} disabled={enviando} onClick={() => navegar(pantalla, 'instructor')}>Instructor</button>
            </div>
            <form key={`${pantalla}-${rol}`} onSubmit={enviar}>
              {pantalla === 'registro' && <label htmlFor="nombre_usuario">Nombre de usuario<input id="nombre_usuario" name="nombre_usuario" autoComplete="username" maxLength={150} required disabled={enviando} placeholder="Cómo te llamamos" /></label>}
              <label htmlFor="ci">CI<input id="ci" name="ci" type="text" inputMode="numeric" pattern="[0-9]{1,20}" maxLength={20} autoComplete={pantalla === 'login' ? 'username' : 'off'} aria-describedby="ci-ayuda" required disabled={enviando} placeholder="Tu número de identificación" /></label>
              <small id="ci-ayuda">Solo números, sin puntos ni guiones.</small>
              <label htmlFor="contrasena">Contraseña<input id="contrasena" name="contrasena" type="password" autoComplete={pantalla === 'login' ? 'current-password' : 'new-password'} required disabled={enviando} placeholder="Tu contraseña" /></label>
              {pantalla === 'registro' && <><small>Usa al menos 8 caracteres. Evita contraseñas comunes, solo numéricas o similares a tu usuario.</small><label htmlFor="confirmar_contrasena">Confirmar contraseña<input id="confirmar_contrasena" name="confirmar_contrasena" type="password" autoComplete="new-password" required disabled={enviando} placeholder="Una vez más" /></label></>}
              <button className="jw-submit" type="submit" disabled={enviando}>{enviando ? 'Procesando…' : pantalla === 'login' ? 'Ingresar' : 'Crear cuenta'}<span aria-hidden="true">↗</span></button>
            </form>
            <nav className="jw-account-links" aria-label="Opciones de cuenta">{pantalla === 'login' ? <><p>¿Primera vez por aquí?</p><button className="enlace" disabled={enviando} onClick={() => navegar('registro', rol)}>Crear cuenta de {rol}</button></> : <button className="enlace" disabled={enviando} onClick={() => navegar('login', rol)}>Ya tengo cuenta. Iniciar sesión</button>}</nav>
            <p className="jw-form-note">{rol === 'instructor' ? 'Tu espacio para proponer y gestionar talleres.' : 'Tu espacio para descubrir e inscribirte a talleres.'}</p>
          </section>
        </div>}
        {!iniciando && pantalla === 'cuenta' && usuario && <section className="acceso jw-account"><h1>Sesión iniciada</h1><p>Hola, {usuario.nombre_usuario}.</p><p>Rol: <strong>{usuario.rol_nombre}</strong></p>{usuario.rol === 'administrador' && <p><a href="/admin/">Abrir Django Admin</a></p>}<button onClick={cerrarSesion} disabled={enviando}>{enviando ? 'Cerrando…' : 'Cerrar sesión'}</button></section>}
      </main>
      <footer className="jw-footer"><span>join.a.workshop<span className="jw-dot">.</span></span><p>Aprender nos conecta.</p><span>Hecho para empezar.</span></footer>
    </div>
  );
}
