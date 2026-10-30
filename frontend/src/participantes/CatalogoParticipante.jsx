import { useEffect, useRef, useState } from 'react';
import {
  cancelarInscripcion, inscribirEnTaller, obtenerCatalogo, obtenerMisInscripciones,
  solicitarEspera, obtenerNotificaciones, marcarNotificacionLeida,
} from './api.js';
import './catalogo.css';

function Notificaciones({ onSesionCaducada, onNovedades }) {
  const [abierto, setAbierto] = useState(false);
  const [nuevoAviso, setNuevoAviso] = useState(null);
  const [bandeja, setBandeja] = useState({ notificaciones: [], no_leidas: 0, siguiente: null });
  const [anteriores, setAnteriores] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [error, setError] = useState('');
  const [ocupado, setOcupado] = useState(null);
  const [cargando, setCargando] = useState(true);
  const ultimo = useRef(null);
  const novedades = useRef(onNovedades);
  novedades.current = onNovedades;
  useEffect(() => {
    const controller = new AbortController();
    let consultando = false;
    async function actualizar() {
      if (consultando || controller.signal.aborted || document.visibilityState === 'hidden') return;
      consultando = true;
      try {
        const datos = await obtenerNotificaciones({ signal: controller.signal });
        if (controller.signal.aborted) return;
        if (!Array.isArray(datos.notificaciones) || !Number.isInteger(datos.no_leidas)) throw new Error('Respuesta inválida de notificaciones.');
        setBandeja(datos);
        setError('');
        const id = datos.notificaciones[0]?.id || '';
        if (ultimo.current !== null && ultimo.current !== id) {
          novedades.current?.();
          if (datos.notificaciones[0]) setNuevoAviso(datos.notificaciones[0]);
        }
        ultimo.current = id;
      } catch (fallo) {
        if (controller.signal.aborted) return;
        if (fallo.status === 401) onSesionCaducada();
        else setError('No pudimos actualizar tus notificaciones. Volveremos a intentarlo.');
      } finally { consultando = false; if (!controller.signal.aborted) setCargando(false); }
    }
    actualizar();
    const timer = window.setInterval(actualizar, 15000);
    window.addEventListener('focus', actualizar);
    document.addEventListener('visibilitychange', actualizar);
    return () => {
      controller.abort(); window.clearInterval(timer);
      window.removeEventListener('focus', actualizar);
      document.removeEventListener('visibilitychange', actualizar);
    };
  }, [onSesionCaducada]);
  useEffect(() => {
    if (!abierto) return undefined;
    const cerrar = (e) => { if (e.key === 'Escape') setAbierto(false); };
    window.addEventListener('keydown', cerrar);
    return () => window.removeEventListener('keydown', cerrar);
  }, [abierto]);
  useEffect(() => {
    if (!nuevoAviso) return undefined;
    const timer = window.setTimeout(() => setNuevoAviso(null), 10000);
    return () => window.clearTimeout(timer);
  }, [nuevoAviso]);
  async function leer(id) {
    if (ocupado) return;
    setOcupado(id);
    try {
      await marcarNotificacionLeida(id);
      setBandeja((actual) => ({ ...actual, no_leidas: Math.max(0, actual.no_leidas - 1),
        notificaciones: actual.notificaciones.map((n) => n.id === id ? { ...n, leida: true } : n) }));
      setAnteriores((actual) => actual.map((n) => n.id === id ? { ...n, leida: true } : n));
      setError('');
    } catch (fallo) {
      if (fallo.status === 401) onSesionCaducada();
      else setError('No se pudo marcar como leída. Inténtalo nuevamente.');
    } finally { setOcupado(null); }
  }
  async function cargarAnteriores() {
    if (ocupado) return;
    setOcupado('pagina');
    try {
      const datos = await obtenerNotificaciones({ antes: cursor || bandeja.siguiente });
      setAnteriores((actual) => [...actual, ...datos.notificaciones]);
      setCursor(datos.siguiente || 'fin');
    } catch (fallo) {
      if (fallo.status === 401) onSesionCaducada();
      else setError('No se pudieron cargar las notificaciones anteriores.');
    } finally { setOcupado(null); }
  }
  const items = [...new Map([...anteriores, ...bandeja.notificaciones].map((n) => [n.id, n])).values()].sort((a, b) => b.fecha.localeCompare(a.fecha) || b.id.localeCompare(a.id));
  return <div className="pw-notificaciones">
    <button className="pw-bell" type="button" aria-label={`Notificaciones, ${bandeja.no_leidas} sin leer`}
      aria-expanded={abierto} aria-controls="bandeja-notificaciones" onClick={() => setAbierto(!abierto)}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></svg>
      {bandeja.no_leidas > 0 && <span className="pw-bell-count">{bandeja.no_leidas > 99 ? '99+' : bandeja.no_leidas}</span>}
    </button>
    {nuevoAviso && <aside className="pw-notification-toast" role="status" aria-live="polite">
      <button className="pw-toast-close" type="button" aria-label="Cerrar aviso" onClick={() => setNuevoAviso(null)}>×</button>
      <span>NUEVA NOTIFICACIÓN</span><strong>{nuevoAviso.titulo}</strong><p>{nuevoAviso.mensaje}</p>
      <button className="pw-toast-open" type="button" onClick={() => { setAbierto(true); setNuevoAviso(null); }}>Ver notificaciones →</button>
    </aside>}
    {abierto && <section id="bandeja-notificaciones" className="pw-notification-panel" aria-label="Tus notificaciones">
      <div className="pw-notification-heading"><div><span>TU ESPACIO, AL DÍA</span><h2>Notificaciones</h2></div><button type="button" aria-label="Cerrar notificaciones" onClick={() => setAbierto(false)}>×</button></div>
      {error && <p className="pw-notification-error" role="alert">{error}</p>}
      {cargando && <p role="status">Consultando notificaciones…</p>}
      {!cargando && !error && items.length === 0 && <p className="pw-notification-empty">Estás al día. Aquí aparecerán las novedades de tus talleres y tu cuenta.</p>}
      <ul>{items.map((n) => <li key={n.id} className={n.leida ? '' : 'pw-notification-unread'}>
        <span className={`pw-notification-type pw-notification-type-${n.tipo}`}>{({ edicion_taller: 'Tu taller', promocion: 'Tu plaza', bloqueo: 'Tu cuenta' })[n.tipo]}</span>
        <h3>{n.titulo}</h3><p>{n.mensaje}</p><time dateTime={n.fecha}>{new Intl.DateTimeFormat('es-BO', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(n.fecha))}</time>
        {!n.leida && <button type="button" disabled={Boolean(ocupado)} onClick={() => leer(n.id)}>Marcar como leída</button>}
      </li>)}</ul>
      {(cursor ? cursor !== 'fin' : bandeja.siguiente) && <button type="button" className="pw-load-notifications" disabled={Boolean(ocupado)} onClick={cargarAnteriores}>Ver anteriores</button>}
    </section>}
  </div>;
}

function FechaTaller({ valor, zona }) {
  const fecha = new Date(valor);
  const dia = new Intl.DateTimeFormat('es-BO', {
    day: '2-digit', month: 'short', year: 'numeric', timeZone: zona,
  }).format(fecha);
  const hora = new Intl.DateTimeFormat('es-BO', {
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: zona,
  }).format(fecha);
  return <time dateTime={valor}>{dia} <span>· {hora}</span></time>;
}

function TarjetaTaller({
  taller, zona, onInscribirme, enviando, modo = 'catalogo', onCancelar, cancelando = false,
}) {
  const [menuAbierto, setMenuAbierto] = useState(false);
  const esMisInscripciones = modo === 'inscripciones';
  const espera = taller.cupos_disponibles === 0;
  const inscrito = Boolean(taller.mi_estado);
  const llena = espera && !(taller.lugares_espera > 0);
  const etiqueta = taller.mi_estado === 'en_espera'
    ? (taller.posicion_espera ? `En espera · Posición ${taller.posicion_espera}` : 'En espera')
    : inscrito ? 'Inscripción confirmada'
    : llena ? 'Lista de espera llena'
    : espera ? 'Entrar en lista de espera' : 'Inscribirme';
  const estado = taller.estado === 'en_espera' ? 'En espera' : 'Confirmada';
  return (
    <article
      className={`pw-card${esMisInscripciones ? ' pw-card-inscripcion' : ''}`}
      aria-labelledby={`taller-${taller.codigo}`}
    >
      <div className="pw-card-top">
        <span className="pw-code">{taller.codigo}</span>
        <div className="pw-card-top-actions">
          <span className={esMisInscripciones
            ? `pw-tag ${taller.estado === 'en_espera' ? 'pw-tag-espera' : 'pw-tag-confirmada'}`
            : 'pw-tag'}
          >
            {esMisInscripciones ? estado : 'Próximamente'}
          </span>
          {esMisInscripciones && onCancelar && (
            <div className="pw-menu-wrap">
              <button
                className="pw-menu-toggle"
                type="button"
                aria-label={`Acciones para ${taller.nombre}`}
                aria-haspopup="menu"
                aria-expanded={menuAbierto}
                onClick={() => setMenuAbierto((abierto) => !abierto)}
                disabled={cancelando}
              >
                ⋯
              </button>
              {menuAbierto && (
                <div className="pw-menu" role="menu">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuAbierto(false);
                      onCancelar(taller);
                    }}
                  >
                    Cancelar inscripción
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <h3 id={`taller-${taller.codigo}`}>{taller.nombre}</h3>
      {taller.descripcion && <p className="pw-description">{taller.descripcion}</p>}
      <dl className="pw-details">
        <div><dt>Inicio</dt><dd><FechaTaller valor={taller.fecha_inicio} zona={zona} /></dd></div>
        <div><dt>Fin</dt><dd><FechaTaller valor={taller.fecha_fin} zona={zona} /></dd></div>
        {esMisInscripciones && taller.instructor && (
          <div><dt>Instructor</dt><dd>{taller.instructor}</dd></div>
        )}
        {esMisInscripciones && taller.fecha_solicitud && (
          <div><dt>Solicitud</dt><dd><FechaTaller valor={taller.fecha_solicitud} zona={zona} /></dd></div>
        )}
      </dl>
      <div className="pw-capacity">
        <span>Cupo máximo</span>
        <strong>{taller.cupos} {taller.cupos === 1 ? 'persona' : 'personas'}</strong>
        {!esMisInscripciones && (
          <>
            <span>Disponibles</span>
            <strong>{taller.cupos_disponibles}</strong>
          </>
        )}
      </div>
      {!esMisInscripciones && (
        <button className="pw-action" type="button" onClick={() => onInscribirme(taller.codigo, espera)} disabled={enviando || inscrito || llena}>
          {enviando ? 'Procesando…' : etiqueta}
        </button>
      )}
    </article>
  );
}

export default function CatalogoParticipante({
  cargarCatalogo = obtenerCatalogo, cargarInscripciones = obtenerMisInscripciones,
  usuario, onCerrarSesion, onSesionCaducada, enviando, error,
}) {
  const [vista, setVista] = useState('catalogo');
  const [estado, setEstado] = useState({ tipo: 'cargando' });
  const [estadoInscripciones, setEstadoInscripciones] = useState({ tipo: 'inactivo' });
  const [intento, setIntento] = useState(0);
  const [intentoInscripciones, setIntentoInscripciones] = useState(0);
  const [codigoEnviando, setCodigoEnviando] = useState(null);
  const [mensajeInscripcion, setMensajeInscripcion] = useState(null);
  const [cancelacionPendiente, setCancelacionPendiente] = useState(null);
  const [cancelando, setCancelando] = useState(false);
  const [mensajeCancelacion, setMensajeCancelacion] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    let vigente = true;
    setEstado({ tipo: 'cargando' });
    cargarCatalogo({ signal: controller.signal })
      .then((datos) => {
        if (vigente) setEstado({ tipo: 'listo', datos });
      })
      .catch((fallo) => {
        if (vigente && fallo.name !== 'AbortError') {
          if (fallo.status === 401) {
            onSesionCaducada();
          } else {
            setEstado({ tipo: fallo.status === 403 ? 'sin-permiso' : 'error' });
          }
        }
      });
    return () => {
      vigente = false;
      controller.abort();
    };
  }, [cargarCatalogo, intento, onSesionCaducada]);

  useEffect(() => {
    if (vista !== 'inscripciones') return undefined;
    const controller = new AbortController();
    let vigente = true;
    setEstadoInscripciones({ tipo: 'cargando' });
    cargarInscripciones({ signal: controller.signal })
      .then((datosInscripciones) => {
        if (vigente) setEstadoInscripciones({ tipo: 'listo', datos: datosInscripciones });
      })
      .catch((fallo) => {
        if (vigente && fallo.name !== 'AbortError') {
          if (fallo.status === 401) {
            onSesionCaducada();
          } else {
            setEstadoInscripciones({ tipo: fallo.status === 403 ? 'sin-permiso' : 'error' });
          }
        }
      });
    return () => {
      vigente = false;
      controller.abort();
    };
  }, [cargarInscripciones, intentoInscripciones, onSesionCaducada, vista]);

  const datos = estado.tipo === 'listo' ? estado.datos : null;
  const datosInscripciones = estadoInscripciones.tipo === 'listo'
    ? estadoInscripciones.datos : null;
  const confirmadas = datosInscripciones
    ? datosInscripciones.inscripciones.filter((inscripcion) => inscripcion.estado === 'confirmada')
    : [];
  const enEspera = datosInscripciones
    ? datosInscripciones.inscripciones.filter((inscripcion) => inscripcion.estado === 'en_espera')
    : [];
  const nombre = datos?.usuario?.nombre || usuario.nombre_usuario;

  function abrirInscripciones() {
    if (vista === 'inscripciones') return;
    setMensajeCancelacion(null);
    setEstadoInscripciones({ tipo: 'cargando' });
    setVista('inscripciones');
  }

  function solicitarCancelacion(taller) {
    setMensajeCancelacion(null);
    setCancelacionPendiente(taller);
  }

  async function confirmarCancelacion() {
    if (!cancelacionPendiente || cancelando) return;
    const taller = cancelacionPendiente;
    setCancelando(true);
    setMensajeCancelacion(null);
    try {
      const resultado = await cancelarInscripcion(taller.codigo);
      setCancelacionPendiente(null);
      setMensajeCancelacion({
        tipo: 'exito',
        texto: resultado.mensaje || 'Cancelación registrada.',
      });
      setIntentoInscripciones((actual) => actual + 1);
      setIntento((actual) => actual + 1);
    } catch (fallo) {
      setCancelacionPendiente(null);
      if (fallo.status === 401) {
        onSesionCaducada();
      } else {
        setMensajeCancelacion({
          tipo: 'error',
          texto: fallo.message || 'No se pudo cancelar la inscripción.',
        });
      }
    } finally {
      setCancelando(false);
    }
  }

  async function inscribirme(codigo, espera = false) {
    if (codigoEnviando) return;
    setCodigoEnviando(codigo);
    setMensajeInscripcion(null);
    try {
      const resultado = await (espera ? solicitarEspera : inscribirEnTaller)(codigo);
      // Conservar el resultado guardado aunque falle la lectura posterior.
      setEstado((actual) => actual.tipo !== 'listo' ? actual : {
        ...actual, datos: { ...actual.datos, talleres: actual.datos.talleres.map((taller) =>
          taller.codigo === codigo ? { ...taller,
            mi_estado: resultado.inscripcion?.estado || (espera ? 'en_espera' : 'confirmada'),
            posicion_espera: resultado.inscripcion?.posicion_espera ?? taller.posicion_espera,
          } : taller) },
      });
      setMensajeInscripcion({ tipo: 'exito', texto: resultado.mensaje || 'Te inscribiste correctamente.' });
      try {
        const actualizado = await cargarCatalogo({});
        setEstado({ tipo: 'listo', datos: actualizado });
      } catch {
        setMensajeInscripcion({
          tipo: 'exito',
          texto: `${resultado.mensaje || 'Solicitud guardada.'} No se pudo actualizar el catálogo; recarga para consultar tu estado.`,
        });
      }
    } catch (fallo) {
      if (fallo.status === 401) {
        onSesionCaducada();
      } else if (fallo.status === 409 || fallo.status === 403 || fallo.status === 404 || fallo.status === 400) {
        setMensajeInscripcion({ tipo: 'error', texto: fallo.message });
        if (fallo.status === 409) {
          try {
            const actualizado = await cargarCatalogo({});
            setEstado({ tipo: 'listo', datos: actualizado });
          } catch { /* El error de inscripción sigue siendo el mensaje principal. */ }
        }
      } else {
        setMensajeInscripcion({ tipo: 'error', texto: fallo.message || 'No se pudo completar la inscripción.' });
      }
    } finally {
      setCodigoEnviando(null);
    }
  }

  return (
    <div className="pw-app">
      <a className="pw-skip" href="#contenido">Ir al contenido</a>
      <header className="pw-header">
        <div className="pw-header-inner">
          <a className="pw-brand" href="#contenido"
            onClick={() => setVista('catalogo')} aria-label="join.a.workshop, ir al catálogo">
            <svg className="jw-join-logo" viewBox="0 0 66 52" fill="none" aria-hidden="true" focusable="false"><path d="M28.26 43.21A18 18 0 1 1 36.79 37.57" stroke="#193c38" strokeWidth="8" /><path d="M37.74 8.79A18 18 0 1 1 29.21 14.43" stroke="#176456" strokeWidth="8" /></svg>
            join.a.workshop<span className="pw-brand-dot">.</span>
          </a>
          <nav className="pw-nav" aria-label="Navegación del participante">
            <button type="button" aria-current={vista === 'catalogo' ? 'page' : undefined}
              onClick={() => setVista('catalogo')}>
              Explorar talleres
            </button>
            <button type="button" aria-current={vista === 'inscripciones' ? 'page' : undefined}
              onClick={abrirInscripciones}>
              Mis inscripciones
            </button>
          </nav>
          <div className="pw-user">
            <Notificaciones onSesionCaducada={onSesionCaducada} onNovedades={() => {
              setIntento((actual) => actual + 1);
              setIntentoInscripciones((actual) => actual + 1);
            }} />
            <span className="pw-avatar" aria-hidden="true">{nombre.charAt(0).toUpperCase()}</span>
            <span className="pw-user-name">{nombre}</span>
            <button className="pw-logout" type="button" onClick={onCerrarSesion} disabled={enviando}>
              {enviando ? 'Cerrando…' : 'Cerrar sesión'}
            </button>
          </div>
        </div>
      </header>
      <main id="contenido" className="pw-main">
        {error && <p className="pw-empty" role="alert">{error}</p>}
        {vista === 'catalogo' ? (
          <>
        <section className="pw-hero" aria-labelledby="titulo-catalogo">
          <div className="pw-hero-copy">
            <p className="pw-eyebrow"><span aria-hidden="true" /> UN ESPACIO PARA SEGUIR APRENDIENDO</p>
            <h1 id="titulo-catalogo">Encontrá tu<br />próximo taller<span>.</span></h1>
            <p className="pw-intro">Explorá nuevas ideas, desarrollá tus habilidades y descubrí lo que viene.</p>
          </div>
          <div className="pw-hero-art" aria-hidden="true">
            <div className="pw-orbit" />
            <div className="pw-art-card pw-art-card-back" />
            <div className="pw-art-card pw-art-card-front"><span>APRENDÉ</span><strong>algo<br />nuevo.</strong><div className="pw-art-lines" /></div>
            <div className="pw-spark"><span className="jw-join-mark" aria-hidden="true" /></div>
          </div>
        </section>
        <section className="pw-listado" aria-labelledby="titulo-listado" aria-busy={estado.tipo === 'cargando'}>
          <div className="pw-section-heading">
            <div><p className="pw-section-label">EXPLORÁ EL CATÁLOGO</p><h2 id="titulo-listado">Próximos talleres</h2></div>
            {datos && <p className="pw-timezone">Horarios en {datos.zona_horaria}</p>}
          </div>
          <p className="pw-help">Consultá las fechas y el cupo máximo de cada taller.</p>
          {mensajeInscripcion && (
            <p className="pw-empty" role={mensajeInscripcion.tipo === 'exito' ? 'status' : 'alert'}>
              {mensajeInscripcion.texto}
            </p>
          )}
          {estado.tipo === 'cargando' && <div className="pw-empty" role="status">Cargando talleres…</div>}
          {estado.tipo === 'sin-permiso' && (
            <div className="pw-empty" role="alert">
              <h3>No tienes permiso para consultar este catálogo</h3>
              <p>Esta sección está disponible para participantes.</p>
            </div>
          )}
          {estado.tipo === 'error' && (
            <div className="pw-empty" role="alert">
              <h3>No pudimos cargar los talleres</h3>
              <p>Revisá tu conexión e intentá nuevamente.</p>
              <button className="pw-action" type="button" onClick={() => setIntento((actual) => actual + 1)}>Reintentar</button>
            </div>
          )}
          {datos && (
            <div className="pw-grid">
              {datos.talleres.length > 0 ? datos.talleres.map((taller) => (
                <TarjetaTaller key={taller.codigo} taller={taller} zona={datos.zona_horaria}
                  onInscribirme={inscribirme} enviando={codigoEnviando !== null} />
              )) : (
                <div className="pw-empty" role="status">
                  <div className="pw-empty-icon" aria-hidden="true"><span className="jw-join-mark" aria-hidden="true" /></div>
                  <h3>No hay talleres disponibles</h3>
                  <p>Volvé pronto para conocer las próximas actividades.</p>
                </div>
              )}
            </div>
          )}
        </section>
          </>
        ) : (
          <section className="pw-mis" aria-labelledby="titulo-mis"
            aria-busy={estadoInscripciones.tipo === 'cargando'}>
            <h1 id="titulo-mis">Mis inscripciones</h1>
            {datosInscripciones && (
              <p className="pw-mis-zona">Horarios en {datosInscripciones.zona_horaria}</p>
            )}
            {mensajeCancelacion && (
              <p className="pw-empty" role={mensajeCancelacion.tipo === 'exito' ? 'status' : 'alert'}>
                {mensajeCancelacion.texto}
              </p>
            )}
            {datosInscripciones?.inscripciones_bloqueadas && (
              <p className="pw-mis-estado" role="alert">
                Tu cuenta está bloqueada para nuevas inscripciones por acumular{' '}
                {datosInscripciones.limite_cancelaciones || 3} cancelaciones consecutivas.
                Contactá a la organización para solicitar la rehabilitación.
              </p>
            )}
            {estadoInscripciones.tipo === 'cargando' && (
              <div className="pw-mis-estado" role="status">Cargando tus inscripciones…</div>
            )}
            {estadoInscripciones.tipo === 'sin-permiso' && (
              <div className="pw-mis-estado" role="alert">
                No tenés permiso para consultar tus inscripciones.
              </div>
            )}
            {estadoInscripciones.tipo === 'error' && (
              <div className="pw-mis-estado" role="alert">
                <p>No pudimos cargar tus inscripciones.</p>
                <button className="pw-action" type="button"
                  onClick={() => setIntentoInscripciones((actual) => actual + 1)}>
                  Reintentar
                </button>
              </div>
            )}
            {datosInscripciones && (
              <div className="pw-mis-columnas">
                <section className="pw-mis-columna" aria-label="Inscripciones confirmadas">
                  {confirmadas.map((inscripcion) => (
                    <TarjetaTaller key={inscripcion.codigo} taller={inscripcion}
                      zona={datosInscripciones.zona_horaria} modo="inscripciones"
                      onCancelar={solicitarCancelacion} cancelando={cancelando} />
                  ))}
                  {confirmadas.length === 0 && (
                    <p className="pw-mis-empty" role="status">No tenés inscripciones confirmadas.</p>
                  )}
                </section>
                <section className="pw-mis-columna" aria-label="Lista de espera">
                  {enEspera.map((inscripcion) => (
                    <TarjetaTaller key={inscripcion.codigo} taller={inscripcion}
                      zona={datosInscripciones.zona_horaria} modo="inscripciones"
                      onCancelar={solicitarCancelacion} cancelando={cancelando} />
                  ))}
                  {enEspera.length === 0 && (
                    <p className="pw-mis-empty" role="status">No tenés solicitudes en espera.</p>
                  )}
                </section>
              </div>
            )}
          </section>
        )}
      </main>
      {cancelacionPendiente && (
        <div className="pw-modal-backdrop">
          <div className="pw-modal" role="dialog" aria-modal="true"
            aria-labelledby="titulo-cancelacion">
            <h2 id="titulo-cancelacion">Cancelar inscripción</h2>
            <p>
              ¿Querés cancelar tu inscripción en <strong>{cancelacionPendiente.nombre}</strong>?
              La cancelación no se puede deshacer.
            </p>
            <div className="pw-modal-actions">
              <button className="pw-action pw-action-secondary" type="button"
                onClick={() => setCancelacionPendiente(null)} disabled={cancelando}>
                Volver
              </button>
              <button className="pw-action" type="button"
                onClick={confirmarCancelacion} disabled={cancelando}>
                {cancelando ? 'Cancelando…' : 'Sí, cancelar'}
              </button>
            </div>
          </div>
        </div>
      )}
      <footer className="pw-footer"><span>join.a.workshop · Espacio del participante</span><span>Aprender nos conecta.</span></footer>
    </div>
  );
}
