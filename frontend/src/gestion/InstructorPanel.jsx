import { useCallback, useEffect, useState } from 'react';
import {
  consultarEspera,
  actualizarTaller,
  crearTaller,
  listarTalleres,
  refrescarSesion,
} from './api.js';

const ZONA_HORARIA = 'America/La_Paz';

function aFechaLocal(valor) {
  const fecha = new Date(valor);
  if (Number.isNaN(fecha.getTime())) return '';
  const partes = new Intl.DateTimeFormat('en-CA', {
    timeZone: ZONA_HORARIA,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(fecha);
  const parte = (tipo) => partes.find((elemento) => elemento.type === tipo)?.value || '';
  return `${parte('year')}-${parte('month')}-${parte('day')}T${parte('hour')}:${parte('minute')}`;
}

function valoresIniciales(taller = null) {
  return taller ? {
    nombre: taller.nombre,
    descripcion: taller.descripcion,
    cupos: taller.cupos,
    fecha_inicio: aFechaLocal(taller.fecha_inicio),
    fecha_fin: aFechaLocal(taller.fecha_fin),
  } : { nombre: '', descripcion: '', cupos: 4, fecha_inicio: '', fecha_fin: '' };
}

export default function InstructorPanel({ usuario, onCerrarSesion, onSesionCaducada }) {
  const [talleres, setTalleres] = useState([]);
  const [editando, setEditando] = useState(null);
  const [datos, setDatos] = useState(valoresIniciales());
  const [cargando, setCargando] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');
  const [mensaje, setMensaje] = useState('');
  const [esperas, setEsperas] = useState({});
  const [consultando, setConsultando] = useState(null);

  async function verEspera(codigo) {
    setConsultando(codigo);
    setError('');
    try {
      const datos = await consultarEspera(codigo);
      setEsperas((actual) => ({ ...actual, [codigo]: datos.solicitudes }));
    } catch (fallo) {
      if (fallo.status === 401) onSesionCaducada();
      else setError(fallo.message);
    } finally { setConsultando(null); }
  }

  const cargar = useCallback(async () => {
    try {
      const resultado = await listarTalleres();
      setTalleres(resultado.talleres);
    } catch (fallo) {
      if (fallo.status === 401) onSesionCaducada();
      else setError(fallo.message);
    } finally { setCargando(false); }
  }, [onSesionCaducada]);

  useEffect(() => { cargar(); }, [cargar]);

  function editar(taller) {
    setEditando(taller.codigo);
    setDatos(valoresIniciales(taller));
    setError('');
    setMensaje('');
  }

  async function guardar(event) {
    event.preventDefault();
    if (enviando) return;
    setEnviando(true);
    setError('');
    setMensaje('');
    try {
      await refrescarSesion();
      const body = { ...datos, cupos: Number(datos.cupos) };
      const resultado = editando
        ? await actualizarTaller(editando, body)
        : await crearTaller(body);
      setMensaje(editando ? 'Cambios guardados. La propuesta vuelve a revisión.' : 'Propuesta enviada para aprobación.');
      setEditando(null);
      setDatos(valoresIniciales());
      await cargar();
      if (resultado.taller) setTalleres((lista) => [resultado.taller, ...lista.filter((t) => t.codigo !== resultado.taller.codigo)]);
    } catch (fallo) {
      if (fallo.status === 401) onSesionCaducada();
      else setError(fallo.message);
    } finally { setEnviando(false); }
  }

  function cambiar(campo, valor) { setDatos((anterior) => ({ ...anterior, [campo]: valor })); }

  const aprobados = talleres.filter((t) => t.estado_aprobacion === 'aprobado').length;
  const pendientes = talleres.filter((t) => t.estado_aprobacion === 'pendiente').length;
  const fechaVisible = (valor) => {
    const fecha = new Date(valor);
    return Number.isNaN(fecha.getTime()) ? 'Sin fecha' : new Intl.DateTimeFormat('es-BO', {
      dateStyle: 'medium', timeStyle: 'short', timeZone: ZONA_HORARIA,
    }).format(fecha);
  };

  return <div className="jw-site iw-app">
    <a className="jw-skip" href="#contenido-instructor">Ir al contenido</a>
    <header className="jw-header iw-header">
      <a className="jw-brand" href="/"><svg className="jw-join-logo" viewBox="0 0 66 52" fill="none" aria-hidden="true" focusable="false"><path d="M28.26 43.21A18 18 0 1 1 36.79 37.57" stroke="#193c38" strokeWidth="8" /><path d="M37.74 8.79A18 18 0 1 1 29.21 14.43" stroke="#176456" strokeWidth="8" /></svg>join.a.workshop<span className="jw-dot">.</span></a>
      <div className="iw-user"><span className="iw-avatar" aria-hidden="true">{usuario.nombre_usuario.charAt(0).toUpperCase()}</span><span>{usuario.nombre_usuario}<small>Instructor</small></span><button className="jw-nav-login" type="button" onClick={onCerrarSesion}>Cerrar sesión</button></div>
    </header>
    <main id="contenido-instructor" className="iw-main">
      <section className="iw-welcome">
        <div><p className="jw-eyebrow"><span /> TU ESPACIO PARA COMPARTIR</p><h1>Lo que sabes,<br /><em>puede abrir caminos.</em></h1><p>Hola, {usuario.nombre_usuario}. Dale forma a tu próxima idea y conviértela en un taller.</p></div>
        <div className="iw-welcome-art" aria-hidden="true"><span><span className="jw-join-mark" aria-hidden="true" /></span><div>Una idea.<br /><strong>Muchas<br />posibilidades.</strong><small>join.a.workshop ↗</small></div></div>
      </section>
      <div className="iw-overview" aria-label="Resumen de talleres">
        <div><span>Mis propuestas</span><strong>{cargando ? '—' : talleres.length.toString().padStart(2, '0')}</strong></div>
        <div><span>Aprobadas</span><strong>{cargando ? '—' : aprobados.toString().padStart(2, '0')}</strong></div>
        <div><span>En revisión</span><strong>{cargando ? '—' : pendientes.toString().padStart(2, '0')}</strong></div>
      </div>
      {error && <p className="jw-notice jw-error" role="alert">{error}</p>}
      {mensaje && <p className="jw-notice" role="status">{mensaje}</p>}
      <div className="iw-workspace">
        <section className="iw-editor" aria-labelledby="form-taller-titulo">
          <div className="iw-editor-heading"><p className="jw-eyebrow">{editando ? 'DALE UNA NUEVA FORMA' : 'DE LA IDEA AL TALLER'}</p><h2 id="form-taller-titulo">{editando ? `Editar ${editando}` : 'Proponer un taller'}</h2><p>Cuéntanos qué quieres compartir. Nosotros te ayudamos a darle un lugar.</p></div>
          <form className="iw-form" onSubmit={guardar}>
            <fieldset disabled={enviando}><legend><span>01</span> Tu propuesta</legend>
              <label>Nombre<input required maxLength="200" value={datos.nombre} onChange={(e) => cambiar('nombre', e.target.value)} placeholder="Dale un nombre a tu próximo taller" /></label>
              <label>Descripción<textarea value={datos.descripcion} onChange={(e) => cambiar('descripcion', e.target.value)} placeholder="¿Qué van a aprender? ¿A quién está dirigido?" /></label>
            </fieldset>
            <fieldset disabled={enviando}><legend><span>02</span> Hazle espacio</legend>
              <label>Cupo máximo<input required type="number" min="4" max="40" value={datos.cupos} onChange={(e) => cambiar('cupos', e.target.value)} aria-describedby="iw-cupo-ayuda" /></label><p id="iw-cupo-ayuda" className="iw-field-help">Entre 4 y 40 participantes.</p>
              <div className="iw-date-fields"><label>Inicio (hora de Bolivia)<input required type="datetime-local" value={datos.fecha_inicio} onChange={(e) => cambiar('fecha_inicio', e.target.value)} /></label><label>Fin (hora de Bolivia)<input required type="datetime-local" value={datos.fecha_fin} onChange={(e) => cambiar('fecha_fin', e.target.value)} /></label></div>
              <p className="iw-field-help">Duración: de 24 horas a 7 días. Horarios en America/La_Paz.</p>
            </fieldset>
            <div className="iw-review-note"><span aria-hidden="true">↗</span><p>{editando ? 'Al guardar los cambios, tu taller vuelve a revisión.' : 'Tu propuesta se revisará antes de aparecer en el catálogo.'}</p></div>
            <button className="jw-button iw-submit" disabled={enviando}>{enviando ? 'Guardando…' : editando ? 'Guardar cambios' : 'Enviar propuesta'}<span aria-hidden="true">↗</span></button>
            {editando && <button type="button" className="jw-text-button" disabled={enviando} onClick={() => { setEditando(null); setDatos(valoresIniciales()); }}>Cancelar edición</button>}
          </form>
        </section>
        <section className="iw-list" aria-labelledby="mis-talleres-titulo">
          <div className="iw-list-heading"><p className="jw-eyebrow">IDEAS QUE YA TOMARON FORMA</p><h2 id="mis-talleres-titulo">Mis talleres <span>{talleres.length}</span></h2><p>Revisa tus propuestas y acompaña cada paso.</p></div>
          {cargando && <p className="iw-empty" role="status">Cargando talleres…</p>}
          {!cargando && talleres.length === 0 && <div className="iw-empty"><span aria-hidden="true"><span className="jw-join-mark" aria-hidden="true" /></span><h3>Tu primera idea empieza aquí.</h3><p>Aún no tienes propuestas. Completa el formulario para crear tu primer taller.</p></div>}
          <div className="iw-cards">
            {talleres.map((taller) => <article className="iw-card" key={taller.codigo}>
              <div className="iw-card-top"><span>{taller.codigo}</span><span className={`iw-status iw-status-${taller.estado_aprobacion}`}>{({ aprobado: 'Aprobado', pendiente: 'En revisión', rechazado: 'Rechazado' })[taller.estado_aprobacion] || taller.estado_aprobacion}</span></div>
              <h3>{taller.nombre}</h3>{taller.descripcion && <p className="iw-card-description">{taller.descripcion}</p>}
              <dl className="iw-card-dates"><div><dt>Inicio</dt><dd>{fechaVisible(taller.fecha_inicio)}</dd></div><div><dt>Fin</dt><dd>{fechaVisible(taller.fecha_fin)}</dd></div></dl>
              <div className="iw-card-capacity"><div><span>Cupo</span><strong>{taller.cupos}</strong></div><div><span>Confirmadas</span><strong>{taller.confirmadas}</strong></div><div><span>Libres</span><strong>{taller.plazas_libres}</strong></div></div>
              <div className="iw-card-actions"><button type="button" disabled={consultando !== null} onClick={() => verEspera(taller.codigo)}>Ver lista de espera</button><button type="button" disabled={enviando} onClick={() => editar(taller)}>Editar y reenviar a aprobación <span aria-hidden="true">↗</span></button></div>
              {consultando === taller.codigo && <p role="status">Consultando espera…</p>}
              {esperas[taller.codigo] && <section className="iw-waitlist" aria-label={`Lista de espera de ${taller.nombre}`}><h4>Lista de espera</h4>{esperas[taller.codigo].length === 0 ? <p>No hay participantes en espera.</p> : <ol>{esperas[taller.codigo].map((solicitud) => <li key={solicitud.posicion}><span>{solicitud.nombre}</span><time dateTime={solicitud.fecha_solicitud}>{fechaVisible(solicitud.fecha_solicitud)}</time></li>)}</ol>}</section>}
            </article>)}
          </div>
        </section>
      </div>
    </main>
    <footer className="jw-footer"><span>join.a.workshop<span className="jw-dot">.</span></span><p>Compartir también es aprender.</p><span>Espacio del instructor</span></footer>
  </div>;
}
