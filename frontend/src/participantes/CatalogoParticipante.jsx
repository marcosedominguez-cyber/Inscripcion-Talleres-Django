import { useEffect, useState } from 'react';
import { inscribirEnTaller, obtenerCatalogo, solicitarEspera } from './api.js';
import './catalogo.css';

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

function TarjetaTaller({ taller, zona, onInscribirme, enviando }) {
  const espera = taller.cupos_disponibles === 0;
  const inscrito = Boolean(taller.mi_estado);
  const llena = espera && !(taller.lugares_espera > 0);
  const etiqueta = taller.mi_estado === 'en_espera'
    ? (taller.posicion_espera ? `En espera · Posición ${taller.posicion_espera}` : 'En espera')
    : inscrito ? 'Inscripción confirmada'
    : llena ? 'Lista de espera llena'
    : espera ? 'Entrar en lista de espera' : 'Inscribirme';
  return (
    <article className="pw-card" aria-labelledby={`taller-${taller.codigo}`}>
      <div className="pw-card-top">
        <span className="pw-code">{taller.codigo}</span>
        <span className="pw-tag">Próximamente</span>
      </div>
      <h3 id={`taller-${taller.codigo}`}>{taller.nombre}</h3>
      {taller.descripcion && <p className="pw-description">{taller.descripcion}</p>}
      <dl className="pw-details">
        <div><dt>Inicio</dt><dd><FechaTaller valor={taller.fecha_inicio} zona={zona} /></dd></div>
        <div><dt>Fin</dt><dd><FechaTaller valor={taller.fecha_fin} zona={zona} /></dd></div>
      </dl>
      <div className="pw-capacity">
        <span>Cupo máximo</span>
        <strong>{taller.cupos} {taller.cupos === 1 ? 'persona' : 'personas'}</strong>
        <span>Disponibles</span>
        <strong>{taller.cupos_disponibles}</strong>
      </div>
      <button className="pw-action" type="button" onClick={() => onInscribirme(taller.codigo, espera)} disabled={enviando || inscrito || llena}>
        {enviando ? 'Procesando…' : etiqueta}
      </button>
    </article>
  );
}

export default function CatalogoParticipante({
  cargarCatalogo = obtenerCatalogo, usuario, onCerrarSesion, onSesionCaducada, enviando, error,
}) {
  const [estado, setEstado] = useState({ tipo: 'cargando' });
  const [intento, setIntento] = useState(0);
  const [codigoEnviando, setCodigoEnviando] = useState(null);
  const [mensajeInscripcion, setMensajeInscripcion] = useState(null);

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

  const datos = estado.tipo === 'listo' ? estado.datos : null;
  const nombre = datos?.usuario?.nombre || usuario.nombre_usuario;

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
          <a className="pw-brand" href="#titulo-listado" aria-label="Talleres, ir al catálogo">
            <span className="pw-brand-icon" aria-hidden="true">T</span>
            Talleres<span className="pw-brand-dot">.</span>
          </a>
          <nav className="pw-nav" aria-label="Navegación del participante">
            <a href="#titulo-listado" aria-current="page">Explorar talleres</a>
          </nav>
          <div className="pw-user">
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
            <div className="pw-spark">✳</div>
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
                  <div className="pw-empty-icon" aria-hidden="true">✳</div>
                  <h3>No hay talleres disponibles</h3>
                  <p>Volvé pronto para conocer las próximas actividades.</p>
                </div>
              )}
            </div>
          )}
        </section>
      </main>
      <footer className="pw-footer"><span>Talleres · Espacio del participante</span><span>Aprender nos conecta.</span></footer>
    </div>
  );
}
