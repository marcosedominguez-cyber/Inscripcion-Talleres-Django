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

  return <main className="acceso gestion-instructor">
    <h1>Gestión de talleres</h1>
    <p>Hola, {usuario.nombre_usuario}. Las fechas se ingresan en hora de Bolivia (America/La_Paz).</p>
    {error && <p className="error" role="alert">{error}</p>}
    {mensaje && <p className="mensaje" role="status">{mensaje}</p>}
    <section aria-labelledby="form-taller-titulo">
      <h2 id="form-taller-titulo">{editando ? `Editar ${editando}` : 'Proponer un taller'}</h2>
      <form onSubmit={guardar}>
        <label>Nombre<input required maxLength="200" value={datos.nombre} onChange={(e) => cambiar('nombre', e.target.value)} /></label>
        <label>Descripción<textarea value={datos.descripcion} onChange={(e) => cambiar('descripcion', e.target.value)} /></label>
        <label>Cupo máximo<input required type="number" min="4" max="40" value={datos.cupos} onChange={(e) => cambiar('cupos', e.target.value)} /></label>
        <label>Inicio (hora de Bolivia)<input required type="datetime-local" value={datos.fecha_inicio} onChange={(e) => cambiar('fecha_inicio', e.target.value)} /></label>
        <label>Fin (hora de Bolivia)<input required type="datetime-local" value={datos.fecha_fin} onChange={(e) => cambiar('fecha_fin', e.target.value)} /></label>
        <button disabled={enviando}>{enviando ? 'Guardando…' : editando ? 'Guardar cambios' : 'Enviar propuesta'}</button>
        {editando && <button type="button" className="secundario" onClick={() => { setEditando(null); setDatos(valoresIniciales()); }}>Cancelar edición</button>}
      </form>
    </section>
    <section aria-labelledby="mis-talleres-titulo">
      <h2 id="mis-talleres-titulo">Mis talleres</h2>
      {cargando && <p role="status">Cargando talleres…</p>}
      {!cargando && talleres.length === 0 && <p>Aún no tienes propuestas.</p>}
      <div className="lista-talleres">
        {talleres.map((taller) => <article key={taller.codigo}>
          <h3>{taller.nombre} <small>{taller.codigo}</small></h3>
          <p>Estado: <strong>{taller.estado_aprobacion}</strong></p>
          <p>Cupo {taller.cupos}; confirmadas {taller.confirmadas}; libres {taller.plazas_libres}</p>
          <p>{taller.descripcion}</p>
          <button type="button" className="secundario" disabled={consultando !== null}
            onClick={() => verEspera(taller.codigo)}>Ver lista de espera</button>
          {consultando === taller.codigo && <p role="status">Consultando espera…</p>}
          {esperas[taller.codigo] && <section aria-label={`Lista de espera de ${taller.nombre}`}>
            <h4>Lista de espera</h4>
            {esperas[taller.codigo].length === 0 ? <p>No hay participantes en espera.</p>
              : <ol>{esperas[taller.codigo].map((solicitud) => <li key={solicitud.posicion}>
                {solicitud.nombre} · <time dateTime={solicitud.fecha_solicitud}>
                  {new Intl.DateTimeFormat('es-BO', { dateStyle: 'short', timeStyle: 'medium', timeZone: ZONA_HORARIA }).format(new Date(solicitud.fecha_solicitud))}
                </time>
              </li>)}</ol>}
          </section>}
          <button type="button" className="secundario" onClick={() => editar(taller)}>Editar y reenviar a aprobación</button>
        </article>)}
      </div>
    </section>
    <button type="button" className="secundario" onClick={onCerrarSesion}>Cerrar sesión</button>
  </main>;
}
