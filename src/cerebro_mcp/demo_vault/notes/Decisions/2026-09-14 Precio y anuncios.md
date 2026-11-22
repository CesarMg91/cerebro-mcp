---
type: decision
date: 2026-09-14
tags: [pricing, decision]
---
# Decisión: precio y anuncios

**Reemplaza a [[Monetization brainstorm]].**

## Qué decidí

- **Pro cuesta $5.99 al mes** (USD) o **$39 al año**.
- **Sin anuncios. Nunca.** Ni en el plan gratis. Un banner en una app que te
  pide constancia se siente como traición, y el SDK de anuncios manda datos que
  no quiero mandar.
- **Prueba gratis de 14 días** de Pro al instalar.
- El plan gratis se queda en 3 hábitos.

## Por qué $5.99 y no $4.99

- En la encuesta de agosto, 6 de 9 testers dijeron que pagarían "unos 6 dólares".
- Sin anuncios, Pro tiene que pagar solo los servidores de sincronización.

## Pendiente

- [x] Cambiar los precios en la página de precios (`streak-web`)
- [ ] Avisarle al agente de `streak-web` que el precio cambió
- [ ] Avisarle al agente de `streak-app` que ya no hay anuncios
- [ ] Actualizar las capturas de la tienda
