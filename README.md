# Early Careers Board

Agregador de stages, alternances, puestos junior/graduate y VIE de multinacionales
en Francia, Alemania, Suiza, Irlanda y Luxemburgo (medtech, banca/finanzas, tech/IA).
Cada oferta enlaza a la página oficial de la empresa. No se copia el texto de las ofertas.

## Cómo funciona
1. `companies.yaml`: lista de empresas (editable).
2. `scraper/jobboard.py`: detecta el ATS de cada empresa (Greenhouse, Lever, Ashby,
   SmartRecruiters, Recruitee, Workable; Workday si lo configuras), descarga las ofertas,
   se queda solo con stages / alternances / junior / VIE en los países elegidos,
   elimina duplicados y escribe `docs/jobs.json`.
3. `docs/index.html`: web estática con filtros (país, sector, tipo, "nuevas esta semana") y
   pestaña de empresas sin feed público.
4. `.github/workflows/update.yml`: actualiza todo cada día, gratis, en GitHub Actions.
5. `scraper/notify.py`: alertas opcionales por Telegram con las ofertas nuevas.

## Puesta en marcha (unos 10 minutos)
1. Crea un repositorio en GitHub y sube esta carpeta.
2. En **Settings > Pages**: Source = "Deploy from a branch", rama `main`, carpeta `/docs`.
3. En la pestaña **Actions**, abre "update-jobs" y pulsa **Run workflow**.
4. Cuando termine (1-3 min), tu web estará en `https://TU_USUARIO.github.io/NOMBRE_REPO/`.
5. Revisa el log del workflow: te dice por empresa qué ATS detectó y cuántas ofertas relevantes encontró.

## Verificar la detección (importante)
El script prueba nombres de empresa como identificador (slug) en cada ATS. Puede acertar con
otra empresa que tenga el mismo nombre. Para comprobarlo:

    pip install -r requirements.txt
    python scraper/jobboard.py --detect

Muestra por empresa el ATS, el slug y una oferta de ejemplo con su URL. Si la URL no es de la
empresa correcta, fija los datos a mano en `companies.yaml`:

    - {name: Mistral AI, sector: tech, ats: lever, slug: mistral}

## Empresas grandes con Workday
Abre una oferta de su web de empleo. Si la URL es
`https://ACME.wd3.myworkdayjobs.com/en-US/ACME_Careers/job/...`, añade:

    - {name: ACME, sector: finance, ats: workday, host: ACME.wd3.myworkdayjobs.com, tenant: ACME, site: ACME_Careers}

Las empresas sin feed público (muchas de banca y medtech) no se rastrean: aparecen en la
pestaña **Companies** con un enlace de búsqueda a su sección de carreras.

## Alertas por Telegram (opcional)
Crea un bot con @BotFather, obtén tu chat id y guarda en **Settings > Secrets and variables > Actions**:
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`. Cada día recibirás solo las ofertas nuevas.

## Pruebas
    python tests/test_offline.py     # clasificación, países y pipeline, sin red

## Límites conocidos
- Una empresa que cambie de ATS deja de aparecer hasta que se reajuste (el log lo indica;
  mientras falla, se conservan sus ofertas anteriores).
- La clasificación es por palabras clave en FR/EN/DE/ES sobre el título: puede dejar pasar
  algún título ambiguo o perder alguno raro. Se ajusta en `classify()`.
- La localización se interpreta con una lista de ciudades y países: ofertas con ubicación
  rara pueden descartarse. Amplía `COUNTRY_WORDS` si lo notas.
- Respeta los términos de uso de cada fuente. Este proyecto usa solo APIs públicas de empleo
  de los ATS y enlaza siempre a la oferta original.
