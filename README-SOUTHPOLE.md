# LUNAPOLE — Shadow & Horizon Planner for the Lunar South Pole

> **Une phrase :** *LUNAPOLE montre, pour n'importe quel point du pôle Sud lunaire, quand le Soleil et la Terre
> sont réellement visibles au-dessus de l'horizon local — en tenant compte de la topographie LOLA, de la
> courbure lunaire, de la libration et du disque solaire étendu.*

[![NASA Space Apps Challenge 2026](https://img.shields.io/badge/NASA%20Space%20Apps%202026-1425C4?style=flat-square)](#)
[![Offline-first](https://img.shields.io/badge/offline-first-00C853?style=flat-square)](#)
[![Python 3.11+](https://img.shields.io/badge/build-3776AB?style=flat-square)](#)
[![TypeScript](https://img.shields.io/badge/app-3178C6?style=flat-square)](#)

---

## Table des matières

1. [Le problème](#1-le-problème)
2. [La proposition : 3 moments « wow »](#2-la-proposition--3-moments-wow)
3. [Ordres de grandeur physiques (le cœur du projet)](#3-ordres-de-grandeur-physiques-le-cœur-du-projet)
4. [Différenciation](#4-différenciation)
5. [Architecture](#5-architecture)
6. [Le pipeline : build hors-ligne vs runtime](#6-le-pipeline-build-hors-ligne-vs-runtime)
7. [Les techniques, une par une](#7-les-techniques-une-par-une)
8. [Structure du dépôt](#8-structure-du-dépôt)
9. [Formats de données](#9-formats-de-données)
10. [API](#10-api)
11. [Spécification UX](#11-spécification-ux)
12. [Précision, validation et intégrité](#12-précision-validation-et-intégrité)
13. [Feuille de route](#13-feuille-de-route)
14. [Risques et critères d'arrêt](#14-risques-et-critères-darrêt)
15. [Licences et attribution](#15-licences-et-attribution)
16. [Ce que ce projet n'est PAS](#16-ce-que-ce-projet-nest-pas)
17. [Glossaire](#17-glossaire)

---

## 1. Le problème

Pour une mission vers le pôle Sud lunaire, deux questions arrivent **en premier**, avant la science :

| Question | Pourquoi c'est bloquant |
|---|---|
| **Énergie solaire** | Combien de temps ce point reçoit-il de lumière ? À quelle élévation ? (le Soleil ne monte jamais à plus de ~1,5° au pôle) |
| **Liaison directe Terre (DTE)** | La Terre est-elle au-dessus de l'horizon local, ou bien le relief la masque-t-il ? |

Les outils existants qui répondent à ces questions sont **réellement mauvais pour ça** :

- `NAIF SPICE` / **JPL Horizons** : fichiers kernel, sortie texte, non documenté pour un non-spécialiste ;
- **Horizons web UI** : sort du texte, pas de topographie, pas d'horizon local ;
- **Moteurs de rendu lunaires** (Cesium, openmoon…) : belle 3D mais **aucune éphéméride correcte**, ce qui veut dire : *faux* ;
- **Outils d'illumination** (ShadowCam, Diviner) : cartes d'images, pas de calcul de site.

Conséquence : un ingénieur peut passer une journée entière à répondre à « est-ce que ce ridge voit la Terre ? ».

**LUNAPOLE rend ça instantané, visuel, et vérifiable.**

---

## 2. La proposition : 3 moments « wow »

Tout le projet est construit autour de trois démonstrations. Pas dix features — **trois**.

### 🎯 W1 — « 1 m de rocher → 38 m d'ombre »

Au pôle Sud, l'élévation solaire maximale est **~1,54°**. La longueur d'ombre est donc :

```
L = h / tan(élévation)   →   à 1,54° :  L ≈ 37 × h
```

**Un rocher d'un mètre projette une ombre de 38 mètres.** C'est immédiatement compréhensible par n'importe quel
public, et ça explique *pourquoi* une erreur de 10 cm sur le DEM change la réponse. Ce n'est pas de la
mathématique : c'est de la physique incarnée.

> Affichage : un curseur « hauteur de l'obstacle » qui dessine l'ombre en direct sur la carte.

### 🎯 W2 — « La Terre ne bouge pas ! »

La intuition dit « la Terre se lève et se couche comme le Soleil ». **Faux au pôle.** Depuis un point lunaire fixe,
la Terre bouge à peine : son mouvement apparent vient essentiellement de la **libration lunaire** (±8°).

Conséquence directe : **les fenêtres de communication directe sont déterminées par le masquage
topographique et par la libration — pas par un mouvement rapide du ciel.** Un site peut être « aveugle à la
Terre » pendant des années, ou avoir une fenêtre quasi-permanente.

**Livrable :** une **carte de visibilité terrestre** — *quels pixels du terrain peuvent voir la Terre, à un moment
ou un autre, sur 18,6 ans ?*

### 🎯 W3 — Le « verdict » en un clic

Un clic n'importe où sur le pôle → **en moins d'une seconde** :

```
Soleil : visible 41 % du temps  ·  élévation mini 0.34°  ·  ombre portée 1 m → 170 m
Terre  : JAMAIS visible (masquée en permanence)
VERDICT : relais-relais obligatoire — DTE impossible
```

C'est ce qui fait qu'un visiteur veut **essayer lui-même**.

---

## 3. Ordres de grandeur physiques (le cœur du projet)

> Ces chiffres sont **les raisons pour lesquelles le projet est intéressant**. Ils sont à valider contre
> JPL Horizons + les produits LRO/LOLA (script `verify/`), mais les ordres de grandeur sont robustes.

### 3.1 Le Soleil au pôle

| Grandeur | Valeur | Conséquence |
|---|---|---|
| Élévation solaire **maximale** | **1,54°** (obliquité lunaire = 1,5424°) | Le Soleil ne « passe jamais au-dessus », il *rase* |
| Diamètre du disque solaire | **0,53°** | À 1,5° d'élévation, la **pénombre est une fraction énorme** du disque |
| Ombre portée | `L ≈ 37 × h` à 1,54° | Un mètre d'obstacle = 37 m d'ombre |
| Distance horizon géométrique | `√(2·R·h)` | h = 5 m → **4,2 km** ; h = 500 m → **41,7 km** |

**Corollaire critique :** à 500 m d'élévation, un sommet situé à 42 km peut masquer le Soleil. C'est
exactement pourquoi le **far-field** est obligatoire (cf. §7.5).

### 3.2 La Terre au pôle

| Grandeur | Valeur | Conséquence |
|---|---|---|
| **Diamètre apparent de la Terre vue du Lune** | **≈ 1,9°** (≈ 3,7 × le Soleil) | Bien plus grand que l'élévation solaire max : la **visibility partielle** compte |
| Parallaxe max (point sub-lunaire) | **≈ 0,26°** | Petite, mais non négligeable face à un horizon de quelques degrés |
| Libration optique | **±7,9°** en longitude, **±6,7°** en latitude | Dominante : c'est elle qui fait *bouger* la Terre |
| Cycle nodal (draconique) | **18,6 ans** | La période à échantillonner pour un PSR honnête |

**Calcul analytique de l'élévation terrestre** (à partir d'un site de sélénographie `(φ, λ)`, point
sub-Terre `(φs, λs)`) :

```
cos θ = sin φ · sin φs + cos φ · cos φs · cos(Δλ)
élévation = 90° − θ
```

Applications :

| Site | Point sub-Terre à l'équateur | Point sub-Terre à −6,7° (lib. Sud) | Point sub-Terre à +6,7° |
|---|---|---|---|
| **φ = −85°** | élév. ≈ **+5,0°** | élév. ≈ **+11,7°** | élév. ≈ **−1,7°** (sous l'horizon !) |
| **φ = −90°** (pôle exact) | élév. ≈ **0°** (pile à l'horizon) | élév. ≈ **+6,7°** | élév. ≈ 0° |

**→ Un site à −85° peut se retrouver SOUS l'horizon terrestre pendant une partie du cycle de 18,6 ans.**
C'est le cœur de W2. Le résultat dépend de la topographie locale → d'où la carte de visibilité.

---

## 4. Différenciation

Analyse d'un panel de projets concurrents (Space Apps 2026 et outils NASA/ESA) :

| Technique | LUNAPOLE | Concurrents fréquents |
|---|---|---|
| Horizon **far-field** jusqu'à ~100 km + courbure lunaire | ✅ | ❌ (2–5 km seulement) |
| **Disque solaire étendu** (0,53°) en angle solide égal → pénombre modélisée | ✅ | ❌ (souvent un point, donc binaire) |
| **Libration lunaire** incluse (±8°) | ✅ | ⚠️ souvent omise (le bug le plus fréquent) |
| Éphéméride DE440 + orientation lunaire | ✅ | ⚠️ séries ELP tronquées (~0,12° → inacceptable ici) |
| Carte de **visibilité terrestre** (18,6 ans) | ✅ | ❌ |
| **Provenance** mesuré / synthétisé par échantillon | ✅ | ❌ |
| **Précision mesurée et publiée** (`npm run verify`) | ✅ | ❌ |
| Autonome, **zéro CDN**, 100 % offline | ✅ | ⚠️ |
| Pannes propres quand le Soleil est sous l'horizon | ✅ | ❌ (l'app semble cassée) |

> **Note honnêteté :** les_stmtats/étoiles/licences des repos cités dans `README-ADVANCED.md` n'ont **pas** pu
> être vérifiés lors de la rédaction. Ces techniques sont documentées ici comme **références d'ingénierie**,
> pas comme faits vérifiés. Ne jamais copier de code sous licence incompatible.

---

## 5. Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  BUILD TIME — Python 3.11 / NumPy / SciPy / GDAL / SpiceyPy                │
│  (exécuté une fois, jamais dans le navigateur)                               │
│                                                                              │
│  ┌──────────────┐   ┌──────────────────┐   ┌────────────────────────────┐    │
│  │ DE440.bsp    │   │ LOLA LDEM_75S    │   │ Calendrier / fiches sites │    │
│  │ moon_pa.bpc  │   │ + curvature      │   │ (coords, provenance)      │    │
│  └──────┬───────┘   └────────┬─────────┘   └─────────────┬──────────────┘    │
│         │                    │                          │                   │
│         ▼                    ▼                          ▼                   │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │ ephemeris bake : sub-solaire, libration, vecteurs Soleil/Terre/BCRS  │    │
│  └──────────────────────────────┬───────────────────────────────────────┘    │
│                                 │                                            │
│  ┌──────────────────────────────▼───────────────────────────────────────┐    │
│  │ HORIZON ENGINE — marche d'horizon far-field 100 km + courbure       │    │
│  │   → profil d'élévation par secteur azimutal (max-par-bin)            │    │
│  │   → profil de la Terre + fraction du disque visible                  │    │
│  └──────────────────────────────┬───────────────────────────────────────┘    │
│                                 │                                            │
│  ┌──────────────────────────────▼───────────────────────────────────────┐    │
│  │ VISION PRODUCTS — carte d'illumination 18,6 ans                      │    │
│  │               carte de visibilité TERRESTRE 18,6 ans (le différenciateur)│  │
│  └──────────────────────────────┬───────────────────────────────────────┘    │
│                                 │                                            │
│                    ┌────────────▼────────────┐                               │
│                    │  artifacts/  (< 15 Mo)  │                               │
│                    │  *.bin, *.json, *.png   │                               │
│                    └────────────┬────────────┘                               │
└─────────────────────────────────┼────────────────────────────────────────────┘
                                  │  copie statique, versionnée dans le dépôt
┌─────────────────────────────────┼────────────────────────────────────────────┐
│  RUNTIME — navigateur, 100 % offline                                             │
│                                 ▼                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ RENDU — Three.js vendored, WebGL2, floating-origin + log depth buffer   │  │
│  │   ├─ Panneau A : carte DEM polaire stereo, éclairée par l'éphéméride   │  │
│  │   ├─ Panneau B : diagramme d'horizon polaire (az/él)                   │  │
│  │   └─ Panneau C : ciel à la 1ʳᵉ personne (Sun + Earth + horizon)        │  │
│  ├────────────────────────────────────────────────────────────────────────┤  │
│  │ LIBRAIRIE DE CALCUL (fallback runtime, ~120 Ko)                        │  │
│  │   cosinekitty/astronomy : Soleil + LIBRATION hors-ligne                │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│  3 panneaux  ←→  curseur temporel (288 pts/jour)  ←→  verdict en 1 clic    │
└────────────────────────────────────────────────────────────────────────────┘
```

### Pourquoi « tout calc hors-ligne »

| Décision | Raison |
|---|---|
| Aucun calcul lourd dans le navigateur | 288 pts/jour × 30 j × 10 sites = ~86 000 vecteurs par vue. En NumPy : **instantané**. En JS avec un pipeline de marches : la freeze. |
| Zéro API au runtime | Le Wi-Fi du jury sature. Une app qui appelle une API en 2026 = écran noir. |
| Bundle < 15 Mo | Lien qui s'ouvre en **3 secondes** au lieu d'une minute. |
| Débogage au build | Les bugs apparaissent dans le terminal, pas pendant la démo. |
| Reproductibilité | Le même artefact sort à chaque build → possible de hasher et publier. |

---

## 6. Le pipeline : build hors-ligne vs runtime

### 6.1 Étape BUILD-1 — Acquisition des données

```
Sources (domaine public / NASA Open Data)
├── DE440.bsp           (éphéméride planétaire, NAIF)          ~114 Mo
├── moon_pa_de440.bpc   (orientation lunaire, NAIF)             ~1 Mo
├── ldem_75s_*.tif      (LOLA gridded, 118 m/px, pôle Sud)      ~1 Go
└── ldem_87s_*.tif      (LOLA gridded, bande 87°S)              ~1 Go
        │
        ▼
Découpe + réduction
├── Crop circulaire ~50 km autour de chaque site cible   (25 m/px)
└── Quantification Int16 + compression (zstd/brotli)
```

**Décision critique : les DEM LOLA complets font ~3,2 Go. Un juge ne les télécharge pas.** On croppe ~50 km
par site et on versionne dans le dépôt : **~50 Mo par site**, le compromis juste.

**Formule de décodage LOLA (à ne pas se tromper) :**

```python
height_m = pixel_value * 0.5 - 1_737_400.0      # R_moon = 1737.4 km
```

Une erreur ici = **tout est décalé de 1,7 million de mètres**. Test unitaire obligatoire.

### 6.2 Étape BUILD-2 — Éphéméride

Pour chaque site, pour chaque pas de temps :

```python
for t in times:                                  # 288 pas de 5 min par jour
    et, lt = et_to_tdb(utc), et_to_tdb(utc)      # TDB, pas UTC
    r_moon = spice.xyz('DE440', et, 'MOON', et)  # BCRS
    rot    = spice.xfrm(et, 'IAU_MOON', et)      # orientation lunaire
    site   = r_moon + R(lat, lon) @ rot          # position du site en BCRS

    sun_dir  = normalize(spice.xyz(et, 'SUN',  site, et))
    earth_dir= normalize(spice.xyz(et, 'EARTH',site, et))
```

Outputs : `sub_solar`, `sub_earth`, `site_bcrs`, `earth_dist_km`, `earth_ang_diam_deg` (≈ 1,9°).

**⚠️ Règle de temps (timescales) :** la rotation de la Terre appartient à **UT1/GMST**, pas au TDB. Ne pas
mélanger. Le repère lunaire body-fixed est défini par une FK, pas par GMST.

### 6.3 Étape BUILD-3 — Horizon far-field (le cœur)

Pour chaque site et chaque secteur azimutal :

1. Tirer **N rayons** (ex. 720 → 0,5°) le long de **grands cercles** sur la sphère lunaire, jusqu'à **100 km**.
2. Pour chaque rayon, échantillonner le DEM tous les ~pixels (pas de pas fixe arbitraire : **pas = le pixel**).
3. **Correction de courbure lunaire** à chaque échantillon (cf. §7.5).
4. Garder le **maximum** d'élévation par secteur (« max-par-bin ») → c'est le profil d'horizon.
5. Écrire le profil + le masque de provenance dans `horizon.bin`.

**Complexité :** ~720 rayons × ~100 km / 120 m ≈ **60 000 échantillons par site par direction** — fait en
quelques secondes en NumPy vectorisé, **impossible** à faire en JS à l'identique.

### 6.4 Étape BUILD-4 — Disque solaire étendu

Pour un instant donné, échantillonner le disque solaire en **angle solide égal** :

```python
R_sun, d = 696_000e3, 149_597_870_700e3      # → 0.2667° de rayon angulaire
N = 512
r_i = R_sun * np.sqrt((np.arange(N) + 0.5) / N)       # ← égalité d'ANGLE SOLIDES
phi_i = (np.arange(N) * 0.618033988749895) % 1.0      # spiral de Fibonacci (répartition uniforme)
```

Puis pour chaque échantillon `s` :

```
V(s) = 1 si élévation(s) > horizon[azimut(s)] + élévation_terrain_locale(s)
flux = Σ_{s: V(s)=1} max(0, n̂ · ŝ) / N
```

Ce qui donne **trois métriques distinctes** (et c'est exactement ce qui manque aux concurrents) :

- `sun_above_horizon` : booléen (Soleil-*lever* géométriquement)
- `disc_fraction` : fraction du disque visible (le **« % du disque au-dessus de l'horizon »**)
- `incident_flux` : flux projeté sur une normale donnée — donc **par panneau orienté**

### 6.5 Étape BUILD-5 — Produits cartes

Sur **18,6 ans** (le cycle nodal complet, sinon on ment) :

- carte d'illumination permanente (PSR) ;
- **carte de visibilité terrestre** (le différenciateur W2) ;
- pour chaque site : séries temporelles illuminée / visible-Terre.

> **Honnêteté obligatoire :** afficher la durée d'échantillonnage dans l'UI.
> « PSR sur 18,6 ans » ≠ « PSR sur 1 an ». Si on n'a pas le cycle complet, **on le dit**.

---

## 7. Les techniques, une par une

### 7.1 Le contrat de frames (à écrire AVANT le code)

C'est le document le plus rentable du projet. Un tableau, rien de plus.

| Frame | Origine | +X | +Y | +Z | Handedness | Unités | Remarque |
|---|---|---|---|---|---|---|---|
| `BCRS` | barycentre du système solaire | — | — | — | droite | km, s | repère barycentrique |
| `ICRF/J2000` | centre Terre (approximé) | — | — | — | droite | km, s | vecteurs du Soleil/Terre |
| `IAU_MOON` (body-fixed) | centre Lune | vers le méridien 0° | est 90°E | nord | **droite** | m, m, m | selénographique |
| `Polaire stéréographique` | pôle Sud | — | — | — | droite | m | projection du DEM |
| `ENU` topocentrique | site | est | nord | **zénith** | droite | m | horizon local |
| `Monde rendu` (Three.js) | caméra | — | — | — | **gauche** | 1 u = 1 km | ⚠️ flip explicite |

**Invariants à ne jamais casser :**

1. **Aucun flip caché de handedness** entre frame scientifique et monde de rendu. Si Three.js impose le
   flip, il est **explicite, nommé et testé**.
2. **Séparer** rotation du corps / translation / registration de texture.
3. **Miroiter horizontalement** la carte stellaire NASA SVS (son RA croît vers la gauche).
4. `1 unité Three.js = 1 km` — sinon les nombres affichés mentent.

### 7.2 Générateur de pseudo-aléatoire déterministe

Pour que les builds soient **reproductibles au bit près** :

```python
SEED = 0x5EED_1A0E
rng  = np.random.default_rng(SEED)      # PCG64, pas MersenneTwister
```

Test d'acceptation : **183/183 artefacts identiques** en 1 thread et en 8 threads.

### 7.3 Correction de courbure lunaire (souvent ignorée → sous-estimation)

Sur une sphère de rayon `R = 1 737 400 m`, la hauteur de la surface au-dessus du plan tangent vaut :

```python
h_sphere = R * (1.0 - np.cos(theta / R))        # theta en mètres d'arc
```

À 30 km, `h_sphere = 42,2 m`. À 100 km, `h_sphere = 469 m`.

**C'est énorme.** L'ignorer revient à sous-estimer la visibilité de la Lune : une crête lointaine qui devrait
masquer le Soleil ne le masque pas dans le calcul. **Et le far-field ne peut que *relever* l'horizon**, donc
l'approximation « champ proche seulement » **surestime toujours l'illumination** (biais « bright »).

### 7.4 Marche d'horizon : « max-par-bin »

```python
AZ_BINS = 720                                 # 0.5° par secteur
horizon = np.full(AZ_BINS, -np.inf)

for ray in rays_on_great_circle(site, az, max_dist=100_000):
    z = sample_dem_with_curvature(ray)        # élévations corrigées
    for b in az_bin_of(ray):
        horizon[b] = np.maximum(horizon[b], z[ray.index[b]])   # ← max, PAS mean
```

**Pourquoi `max` et pas `mean` :** le premier obstacle qui masque le Soleil est le seul qui compte. Une moyenne
sous-estime le risque d'obscurcissement (biais « bright »). C'est la méthode décrite par Mazarico et al. (2011)
*à confirmer dans la référence exacte* — le principe (échantillonnage angulaire + fusion par secteur) est
en revanche standard en télédétection.

### 7.5 Échantillonnage « far-field » adaptatif

```
pôle Sud :  h = 5 m  → horizon géométrique à  4,2 km
            h = 100 m → horizon géométrique à 18,6 km
            h = 500 m → horizon géométrique à 41,7 km   ← un sommet à 42 km masque le Soleil
```

La distance max n'est donc **pas** un choix arbitraire : c'est une **donnée d'entrée**. On l'expose dans l'UI
(`near-field 5 km` vs `far-field 100 km`) pour **démontrer** l'effet, pas pour le cacher.

### 7.6 Éphéméride : DE440 (build) + fallback navigateur

| Contexte | Source | Pourquoi |
|---|---|---|
| Build (autorité) | `DE440.bsp` via SpiceyPy + `moon_pa_de440.bpc` | Précision machine, orientation lunaire correcte |
| Runtime (démo/dégradé) | `cosinekitty/astronomy` (~116 Ko, MIT) | Zéro install, zéro API, offline, **gère la libration** |

**⚠️ Piège documenté :** une série lunaire tronquée (ELP court) donne **~0,12°** d'erreur. Au pôle, 0,12° ≈
**13 m de déplacement horizontal apparent** face à une élévation solaire max de 1,5°. **Inacceptable.** → DE440
obligatoire pour toute affirmation quantitativa.

### 7.7 Libration lunaire — le bug n°1 des visualisations

La libration optique est de **±7,9° en longitude** et **±6,7° en latitude**. Au pôle, c'est *elle* qui fait
bouger la Terre et le point sub-solaire.

**Test de non-régression :** la position du point sub-solaire calculée doit être comparée à
`JPL Horizons` sur au moins **5 epochs** (dont deux où la libration est maximale). Si l'erreur > 0,01° → la
libration n'est pas correctement appliquée.

### 7.8 Terre : parallaxe, diamètre apparent, visibilité partielle

```python
# élévation Terre topocentrique
cos_theta = sin(lat_site) * sin(lat_subearth) \
          + cos(lat_site) * cos(lat_subearth) * cos(lon_site - lon_subearth)
elev_earth = 90 - degrees(arccos(clip(cos_theta, -1, 1)))

# diamètre apparent (≈ 1.9°, PAS 0.5° : c'est le Soleil qui fait 0.53°)
ang_diam = 2 * degrees(arcsin(6378.1e3 / distance_site_earth))

# fraction du disque terrestre au-dessus de l'horizon
disc_fraction_earth = fraction_of_disc(elev_earth, ang_diam, horizon_azimuth)
```

**Pourquoi `disc_fraction_earth` compte :** la Terre fait 1,9° de diamètre apparent, soit **1,23× l'élévation
solaire maximale**. Un site dont le centre de la Terre est 1° sous l'horizon peut encore « voir » une fraction
de son disque. Pour une antenneDirective DTE (Ka 0,7 m), la géométrie du **bord visible** compte autant que
l'angle central.

### 7.9 Pannes propres : « écran noir »

Au pôle, le Soleil est sous l'horizon **la plupart du temps**. Une app naïve ressemble à une app cassée.

**Règle :** jamais d'écran vide. Toujours afficher :

```
⚠️ SOLEIL SOUS L'HORIZON
   Élévation actuelle : −0,42°
   Prochaine lever : 2028-04-17 09:32 UTC   (dans 138 j)
   Raison : occultation par le relief, à 12,4 km au NNE (crête Shackleton)
   Disque visible : 0,0 %  ·  Profondeur du soleil : 0,68°
```

C'est la différence entre « ça ne marche pas » et « **la science dit que non** ».

### 7.10 Rendu : floating-origin + log depth

Si l'observateur est sur Shackleton à l'échelle 1:1 **et** la Terre est affichée à sa vraie distance
(≈ 384 400 km), le rapport de profondeurs est **~10⁷**. Le depth buffer naïf produit du z-fighting partout.

```js
// au lieu de translater la caméra de 384 400 km :
const rel = worldPos.clone().sub(camera.position);  // on garde la caméra près de l'origine
renderer.setPixelRatio(1);
scene.add(camera.position.clone());                  // et on décale le monde
// + logarithmicDepthBuffer: true
```

### 7.11 Ombres de terrain : PCF minimum

```glsl
// PCF (Percentage-Closer Filtering) + bias proportionnel à la pente
float bias = max(0.0015 * (1.0 - dot(N, L)), 0.0004);
```

Sans PCF, les ombres de terrain au pôle — où tout est rasant — sont du bruit. Et comme le flux est
réellement calculé (§7.4), **l'ombre affichée et le flux calculé doivent venir de la même source**, sinon l'écran
contredit le tableau.

### 7.12 Intégrité : provenance, fail-closed, précision publiée

```json
{
  "t": 1771392000.0,
  "elevation_source": {"r8": 0b01011001},
  "provenance_note": "m=mesuré (LOLA), s=synthétisé (interpolation)",
  "dem_id": "ldem_75s_118m_2048",
  "dem_gap_fill": "none"
}
```

**Trois règles non négociables :**

1. **Fail-closed** : DEM absent → erreur bruyante. **Jamais** de fallback analytique silencieux. C'est
   exactement comme ça que ces apps finissent *subtilement fausses*.
2. **Provenance par échantillon** : chaque élévation est marquée mesurée ou synthétisée.
3. **Précision publiée** : `npm run verify` compare à JPL Horizons et affiche le chiffre
   (*ex. « erreur max 0,0111° sur le point sub-solaire, 2020-2049 »*). Un chiffre mesuré convainc
   incomparablement plus que « nos résultats sont corrects ».

### 7.13 Ce qu'on ne fait PAS

| Technique du README source | Décision | Raison |
|---|---|---|
| Lecteur DE440 en TypeScript (dans le navigateur) | **Non** | Bake suffit ; coût élevé, gain jury nul |
| BVH ray tracing + Crank-Nicolson (thermique) | **Non** | C'est un mémoire de master, pas 48 h |
| Quadtree / culling OBB / LOD | **Non** | Crop de 50 km → un mesh statique suffit |
| ML / XGBoost / SHAP | **Non (par défaut)** | Le plus faible scientifiquement, le plus verbeux. Optionnel en fin de projet, et seulement si honnête |
| Effets de parallaxe « foveated » | **Non** | Coût de dev, zéro gain |

---

## 8. Structure du dépôt

```
lunapole/
├── README.md                       ← ce fichier
├── docs/
│   ├── frames-contract.md           ← OBLIGATOIRE, à écrire en premier
│   ├── data-provenance.md           ← ce qui est mesuré, ce qui est synthétisé
│   └── adr/                         ← Architecture Decision Records
│       ├── 0001-why-the-sun-is-not-a-slider.md
│       ├── 0002-psr-needs-18-6-years.md
│       └── 0003-near-field-only-errs-bright.md
│
├── build/                           ← Python : tout le calcul lourd
│   ├── pyproject.toml
│   ├── lunapole/
│   │   ├── frames.py                # contrat de frames, transformations
│   │   ├── ephemeris.py             # SpiceyPy → sub-solaire, libration, vecteurs
│   │   ├── dem.py                   # lecture LOLA, décodage, courbure
│   │   ├── horizon.py               # marche far-field 100 km + max-par-bin
│   │   ├── solar_disc.py            # échantillonnage en angle solide égal
│   │   ├── earth.py                 # élévation, parallaxe, disque visible
│   │   ├── maps.py                  # PSR 18,6 ans + carte de visibilité terrestre
│   │   └── bake.py                  # orchestration → artifacts/
│   └── tests/
│       ├── test_dem_decode.py       # piège du 1 737 400
│       ├── test_curvature.py
│       ├── test_reproducibility.py  # artefacts identiques 1 thread vs 8
│       └── golden/
│
├── artifacts/                       ← baked, versionné (< 15 Mo)
│   ├── manifest.json                # checksums SHA-256 de chaque fichier
│   ├── ephemeris/<site>.bin
│   ├── horizon/<site>.bin
│   ├── maps/illumination_18y.png
│   └── maps/earth_visibility_18y.png
│
├── app/                             ← TypeScript / Vite / Three.js
│   ├── src/
│   │   ├── astro/                   # fallback runtime (astronomy-engine)
│   │   ├── render/                  # 3 panneaux, floating-origin, PCF
│   │   ├── timeline/                # 288 pts/jour, scrubber
│   │   ├── verdict/                 # moteur de verdict (W3)
│   │   └── i18n/                    # fr / en / ar
│   └── public/vendor/three/         # ⚠️ VENDORISÉ, jamais de CDN
│
├── verify/                          ← la preuve
│   ├── verify_vs_horizons.py        # chiffre d'erreur publié
│   └── verify_vs_mazarico.py
│
└── site/                            ← page d'accueil FR/EN/AR (30 s de lecture)
```

---

## 9. Formats de données

### 9.1 Éphéméride — `ephemeris/<site>.bin`

Binaire, **Float32 big-endian**, records de 5 min :

| Offset | Type | Champ |
|---|---|---|
| 0 | f32 ×2 | `sub_solar_lat`, `sub_solar_lon` (°) |
| 8 | f32 ×2 | `sub_earth_lat`, `sub_earth_lon` (°) |
| 16 | f32 | `earth_dist_km` |
| 20 | f32 | `earth_ang_diam_deg` |
| 24 | i16 | `provenance_mask` (bits : mesuré/synthétisé par champ) |

288 records/jour × 4 octets × 5 champs ≈ **23 Ko par site et par jour deBake**. 10 sites × 5 ans ≈ 11 Mo
compressé. Acceptable.

### 9.2 Horizon — `horizon/<site>.bin`

```c
typedef struct {
  int32_t   az_bins;              // 720 (0.5°/bin)
  float     elev_deg[720];        // élévation max de l'horizon, corrigée courbure
  float     shadow_dist_km[720];  // distance de l'obstacle masquant
  uint16_t  far_field_mask;       // bins calculés jusqu'à 100 km vs 5 km
  uint8_t   provenance[720];      // 0 = mesuré, 1 = synthétisé, 2 = gap (fail-closed)
} HorizonProfile;                 // ≈ 6,5 Ko par site
```

### 9.3 Carte de visibilité terrestre — le différenciateur

```json
{
  "id": "earth_visibility_18y",
  "period_years": 18.6,
  "period_label": "cycle nodal complet",
  "sample_step_hours": 1.0,
  "sample_count": 162_614,
  "raster": { "width": 2048, "height": 2048, "crs": "polar_stereo_south", "scale_m": 48.8 },
  "channels": {
    "R": "première date de visibilité de la Terre (jours depuis J2000, saturé à 7300)",
    "G": "durée totale de visibilité sur 18,6 ans (fraction 0-255)",
    "B": "élévation max de la Terre (°/14 × 255)"
  },
  "provenance": "terrain mesuré LOLA ; visibilité synthétisée par échantillonnage horodaté"
}
```

---

## 10. API

Le navigateur est **autonome**, mais on expose la même surface pour (a) le débogage, (b) le mode
« mission planner », (c) les tests de régression.

| Endpoint | Rôle |
|---|---|
| `GET /health` | `{"status":"ok","artifacts":[…],"manifest_sha256":"…"}` |
| `GET /api/sites` | Catalogue des sites (coords officiales, provenance du nom) |
| `GET /api/horizon?lat=&lon=` | Profil d'occlusion 360° + flags far-field |
| `GET /api/timeline?lat=&lon=&date=` | **288 points** (5 min) : élévation/azimut Soleil **et** Terre |
| `GET /api/sun?lat=&lon=&t=` | Élévation, azimut, **fraction du disque**, point sub-solaire |
| `GET /api/earth?lat=&lon=&t=` | Élévation, azimut, diamètre apparent, fraction du disque visible |
| `GET /api/verdict?lat=&lon=&from=&to=` | Le verdict W3 (solaire, DTE, ombres, période couverte) |
| `GET /api/map/earth_visibility` | Carte 18,6 ans (PNG + stats) |
| `GET /api/terrain_gltf?lat=&lon=` | Terrain 3D (glTF, pré-exporté) |
| `GET /api/stereo_to_lonlat?x=&y=` | Polaire stéréographique → lat/lon (inverse de la projection) |

> Si l'app est 100 % client (recommandé), ces routes sont implémentées comme **fonctions pures** du même
> module, plus un petit serveur de dev. Une seule implémentation, deux usages.

---

## 11. Spécification UX

### Les 3 panneaux (réponse immédiate à « où sont le Soleil et la Terre par rapport à l'horizon ? »)

```
┌──────────────────────────────┬─────────────────────┬────────────────────────┐
│ A — CARTE POLAIRE ÉCLAIRÉE   │ B — DIAGRAMME        │ C — CIEL 1ʳᵉ PERSONNE   │
│ projection stéréo           │ D'HORIZON            │ dôme céleste lunaire   │
│ • ombres portées réelles     │ • az 0-360°          │ • Soleil + Terre réels │
│   (calculées par le flux,    │ • élévation horizon  │ • silhouette du relief │
│   pas une light fixe)        │ • disque Soleil      │ • curseur de temps     │
│ • clic = sélectionner       │ • azimut/élév. S/E   │ • 1 m d'ombre = 38 m   │
└──────────────────────────────┴─────────────────────┴────────────────────────┘
   ──  CURSEUR TEMPOREL : 288 points/jour · play/pause · 2026 → 2050  ──
   ──  BANNIÈRE D'ÉTAT : voir §7.9  ──
```

### Catalogue de sites (coordonnées = source canonique : **USGS/IAU Gazetteer of Planetary Nomenclature**)

| Site | Lat | Lon | Intérêt |
|---|---|---|---|
| Shackleton | −89,92° | 175,1° | Rim polaire, accès au PSR voisin |
| de Gerlache-Kocher Massif | −86,1° | 91,8° | Région Artemis III |
| Connecting Ridge | −85,45° | 31,4° | Corridor Artemis III, accès au pôle |
| Nobile Rim 1 / 2 | −85,72° | 49,65° | Région Artemis III |
| Haworth | −85,88° | 310,4° | CLPS |
| Malapert Massif | −85,45° | 30,1° | CLPS, pic de lumière quasi-perm |
| Mount Mouton | −86,08° | 45,0° | CLPS |
| Leibnitz-β plateau | −85,38° | 30,1° | Nappe de glace Candidate |
| Cabeus / Cabeus B | −84,9° | 309,5° | PSR, accès à Head crater |

> ⚠️ Les coordonnées définitives viennent du **Gazetteer IAU**, pas de ma mémoire. Vérifier avant de figer.

### Le verdict (W3) — format imposé

```
┌────────────────────────────────────────────────────────────────┐
│  SITE : Shackleton Rim   −89.923°,  175.106°   alt +1860 m   │
├────────────────────────────────────────────────────────────────┤
│  ☀️ SOLEIL                                                       │
│     au-dessus de l'horizon :      99,84 % du temps (sur 18,6 a)│
│     élévation mini (long terme) : 0,34°                          │
│     élévation au moment t :      1,21°                          │
│     disque visible maintenant :   100 %                         │
│     ombre portée (obs. 1 m) :     47 m                          │
├────────────────────────────────────────────────────────────────┤
│  🌍 TERRE                                                        │
│     visible au-dessus de l'horizon :  61,2 % du temps           │
│     élévation mini sur 18,6 ans :   −1,72°  ⚠️                │
│     diamètre apparent :              1,90°                       │
│     fenêtre DTE continue max :      6,4 ans                     │
├────────────────────────────────────────────────────────────────┤
│  ✅ VERDICT : énergie solaire excellente. DTE possible en        │
│     fenêtres longues mais INSTABLE — relais lunaire requis.     │
├────────────────────────────────────────────────────────────────┤
│  Données : LOLA LDEM_75S (mesuré) · DE440 (mesuré)             │
│  Couverture : 18,6 ans (cycle nodal complet) ✅                 │
│  Précision : erreur max 0,0111° sur le point sub-solaire        │
└────────────────────────────────────────────────────────────────┘
```

### Bandeau d'état (obligatoire, §7.9)

Le cas « écran noir » est le **taux d'échec n°1** de ce type d'app. Traitement : toujours afficher la cause et la
prochaine occurrence.

---

## 12. Précision, validation et intégrité

### 12.1 Sources de vérité

| Grandeur | Référence | Tolérance cible |
|---|---|---|
| Vecteur Soleil (BCRS) | JPL Horizons | **< 0,01°** |
| Vecteur Terre (BCRS) | JPL Horizons | **< 0,01°** |
| Point sub-solaire | JPL Horizons / publication LRO | **< 0,01°** |
| Libration (α, δ, W) | `moon_pa_de440.bpc` | **< 0,005°** |
| Altitude du site | LOLA LDEM_75S | 118 m/px (résolution native) |
| Horizon | auto-consistant (DEM 118 m/px) | **±1–2°** sur pentes rases |
| Diamètre apparent Terre | Trigonométrie exacte | — |

**À dire honnêtement dans le README :** avec un DEM à 118 m/px, l'horizon a une incertitude de l'ordre de 1 à 2°
sur les fortes pentes. Ce n'est pas rédhibitoire (l'élévation solaire max est 1,54°, donc l'incertitude est du
même ordre que le signal — **et c'est exactement pour ça qu'il faut le publier**).

### 12.2 Les tests qui comptent

```python
# 1. Décodage LOLA — le piège du million de mètres
def test_lola_decode(): assert decode(3474800) == pytest.approx(0.0, abs=1e-6)

# 2. Courbure — 30 km → 42 m
def test_curvature_at_30km(): assert h_sphere(30_000) == pytest.approx(42.2, abs=0.5)

# 3. Reproducibité — 183/183 artefacts identiques, 1 thread vs 8
def test_bitwise_reproducible(): ...

# 4. Non-régression libration — 5 epochs dont 2 à libration max
def test_subsolar_point_matches_horizons(): assert max_err_deg < 0.01

# 5. L_disk = 37 × h  à élévation 1,54°
def test_shadow_length(): assert L(1.0, 1.5424) == pytest.approx(37.2, abs=0.3)

# 6. Biais « bright » — le far-field ne peut QUE relever l'horizon
def test_farfield_never_lowers_horizon():
    assert np.all(horizon_farfield >= horizon_nearfield - 1e-9)
```

Le test n°6 est celui qui prouve que l'algorithme est **conservateur dans le bon sens** : plus de terrain ne peut
qu'*occuler* davantage. Si un test échoue, on a une erreur de signe quelque part.

### 12.3 Intégrité — les 3 règles non négociables

1. **Fail-closed** : DEM manquant / kernel manquant → **erreur bruyante**, jamais de substitution silencieuse.
2. **Provenance par échantillon** : mesuré vs synthétisé, affiché dans l'UI.
3. **Précision mesurée publiée** : `python verify/verify_vs_horizons.py` → un chiffre dans le README.

---

## 13. Feuille de route

Format : **48 h de développement réel** (~12–15 h de codage effectif).

| Nuit | Contenu | Critère de fin |
|---|---|---|
| **N1** | `docs/frames-contract.md` · bake DE440 + 288 pts/jour · squelette Vite + 3 panneaux · fallback astronomy-engine | Les 3 panneaux s'affichent avec un Soleil calculé (pas un slider) |
| **N2** | Horizon far-field **hors-ligne** (Python/NumPy) + courbure · disque étendu + pénombre · tests §12.2 | `% du disque au-dessus de l'horizon` correct · test courbure vert |
| **N3** | 🎯 **Carte de visibilité terrestre 18,6 ans** + animation Terre · moteur de verdict (W3) · bannière §7.9 | **Le verdict s'affiche en < 1 s au clic** |
| **N4** | Zéro-CDN + test téléphone + mode avion · page d'accueil FR/EN/AR · README avec chiffres · polish visuel | Lien ouvert en 3 s sur téléphone, sans réseau |
| **+** | ML / SHAP — **uniquement** si tout le reste est terminé et vérifié | Optionnel, jamais à la place du reste |

---

## 14. Risques et critères d'arrêt

| Risque | Impact | Mitigation |
|---|---|---|
| **Le far-field est trop lent** | Le build dépasse la nuit | Vectoriser NumPy, `--workers`, `--skip-existing`. Si > 20 min : réduire à 50 km |
| **Téléphonie/browser plante le rendu** | Démo ratée | Trois.js vendored, `powerPreference`, `antialias: false`, budget < 15 Mo |
| **Le bundle est trop lourd** | Lien qui ne charge pas | WebP pour les cartes, Int16 pour le DEM, zstd pour le binaire |
| **La carte 18,6 ans prend 6 h** | Pas le temps | Décimation ×4 (≈ 1220²) + échantillonnage temporel adaptatif |
| **La Terre « bouge trop peu » → animation ennuyeuse** | Le wow moment rate | Animer **la libration + le masque topographique**, pas la position. Ajouter un **coupe-soleil** au moment où l'Terre entre dans le champ |
| **Un juge trouve le point faible scientifique** | Crash de crédibilité | Le README assume : DEM 118 m → horizon ±1–2°. On publie la limite |
| **Le temps manque** | Livraison partielle | **Critère d'arrêt :** si à N3 on n'a pas la carte terrestre + le verdict, on coupe tout le reste et on livre |

---

## 15. Licences et attribution

| Ressource | Licence | Action |
|---|---|---|
| LOLA LDEM (PDS / USGS Astrogeology) | **Domaine public US** | Attribution NASA/USGS requise |
| LRO / LROC (WAC, NAC) | **Domaine public US** | Attribution requise |
| DE440.bsp, `moon_pa_de440.bpc` (NAIF) | Public | Citer NAIF/JPL |
| Images NASA SVS (CGI Moon Kit, Deep Star Maps) | Domaine public | Attribution requise |
| `cosinekitty/astronomy` | MIT | ✅ sûr — attribution requise |
| `SpiceyPy` | MIT | ✅ sûr |
| **USGS/IAU Gazetteer of Planetary Nomenclature** | — | **Source canonique pour les noms et coordonnées** |

**⚠️ Lignes rouges :** ne jamais copier de code sous **AGPL-3.0** ou **sans licence**. Étudier les concepts est
légitime ; copier le code ne l'est pas. Vérifier chaque licence avant d'intégrer quoi que ce soit.

---

## 16. Ce que ce projet n'est PAS

L'honnêteté fait partie de la note. LUNAPOLE :

- **n'est pas** un moteur d'illumination temps réel pour une mission en vol (pas d'OM, pas de propagation
  d'incertitude d'attitude) ;
- **n'est pas** un outil de navigation ou de planification de trajectoire ;
- **ne modélise pas** la thermique, le régime des poussières, le plasma, ni les satellites de relais ;
- **ne remplace pas** SPICE pour un usage opérationnel — il s'appuie dessus ;
- **est un instrument d'analyse de site et de crédibilité**, avec une couche pédagogique — pas un simulateur.

Si on ne sait pas, on ne simule pas : on **échoue visiblement** (§12.3, règle 1).

---

## 17. Glossaire

| Terme | Définition |
|---|---|
| **É Elevation topocentrique** | Hauteur d'un astre au-dessus de l'horizon **local** (pas au-dessus du plan de référence) |
| **Libration** | Balancement apparent de la Lune ; ±7,9° lon, ±6,7° lat au pôle |
| **PSR** | Permanently Shadowed Region — région ombrée en permanence |
| **Cycle nodal / draconique** | 18,6 ans — période de précession du nœud lunaire |
| **Far-field horizon** | Horizon calculé jusqu'à ~100 km (et non 2–5 km) |
| **Pénombre** | Fraction du disque solaire occultée par le relief |
| **DTE** | Direct To Earth — liaison directe satellite ↔ station au sol |
| **Point sub-solaire / sub-Terre** | Point de la surface lunaire le plus proche du Soleil / de la Terre |
| **Angle solide** | Aire angulaire vue depuis un point (ici : le disque solaire) |
| **Near/far field** | Zone proche / lointaine du terrain prise en compte |
| **Stéréographique polaire** | Projection cartographique de la projection polaire pour les DEM |
| **Sélénographie** | Système de coordonnées fixées à la Lune (lat/lon lunaires) |

---

## 18. Contact / contributions

- Données : **NASA Open Data** (LOLA, LRO/LROC, NAIF kernels) — domaine public US.
- Noms et coordonnées : **USGS/IAU Gazetteer of Planetary Nomenclature**.
- Cadre : **NASA Space Apps Challenge 2026** — les questions traités correspondent aux besoins de *Artemis III* /
  *CLPS* (solar access & direct-to-Earth).
- Contributions bienvenues : ouvrir une issue avec la référence JPL Horizons correspondante.