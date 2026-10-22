/* AFC ACE dashboard panel for the Mainsail Panel Extender.
 *
 * A spool tile per lane (color + material) for each ACE unit the cosmoace_afc
 * driver runs, a dryer section per unit, and a lane editor with a color
 * wheel for manual (non-RFID) spools. Stands in for Mainsail's own AFC
 * panel (`replaces`).
 *
 * Reads the driver's and AFC's Klipper objects (AFC_ACE <unit>,
 * AFC_lane <lane>, AFC) with plain object queries, so it stays live during
 * prints. Writes go through AFC's SET_COLOR / SET_MATERIAL, which persist to
 * AFC.var and publish lane_data for OrcaSlicer, and the driver's
 * AFC_ACE_DRYER_START / AFC_ACE_DRYER_STOP.
 *
 * Safe without the Panel Extender: nothing loads this file. */
;(function () {
    if (!window.CosmosPanels) return

    var ACE_TYPES = ['PLA', 'PETG', 'ABS', 'ASA', 'TPU', 'HIPS', 'PC']
    var POLL_MS = 3000

    // units: [{ name, status }] in config order; lanes: name -> AFC_lane status
    var unitObjs = [], laneObjs = []
    var units = [], lanes = {}, cur = null, printing = false, err = ''
    var dryDefaults = { t: 45, m: 240 }
    var renderFn = null, pollTimer = null

    var esc = function (s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    }
    // dryer remain_time arrives in seconds
    var fmtRemain = function (sec) {
        sec = +sec || 0
        var h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60)
        return h ? h + ' h ' + m + ' min' : m + ' min'
    }

    /* ---------------- color helpers ---------------- */
    function hsv2hex(h, s, v) {
        var f = function (n) {
            var k = (n + h / 60) % 6
            var c = v - v * s * Math.max(0, Math.min(k, 4 - k, 1))
            return Math.round(c * 255).toString(16).padStart(2, '0')
        }
        return '#' + f(5) + f(3) + f(1)
    }
    function hex2hsv(x) {
        var r = parseInt(x.slice(1, 3), 16) / 255
        var g = parseInt(x.slice(3, 5), 16) / 255
        var b = parseInt(x.slice(5, 7), 16) / 255
        var mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn
        var h = 0
        if (d) {
            if (mx === r) h = 60 * (((g - b) / d) % 6)
            else if (mx === g) h = 60 * ((b - r) / d + 2)
            else h = 60 * ((r - g) / d + 4)
        }
        if (h < 0) h += 360
        return { h: h, s: mx ? d / mx : 0, v: mx }
    }

    /* ---------------- minimal modal ---------------- */
    function openModal(html) {
        var ov = document.createElement('div')
        ov.style.cssText =
            'position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.55);' +
            'display:flex;align-items:center;justify-content:center'
        var dark = !document.querySelector('.v-application.theme--light')
        var card = document.createElement('div')
        card.className = 'v-card v-sheet ' + (dark ? 'theme--dark' : 'theme--light')
        card.style.cssText =
            'width:340px;max-width:92vw;border-radius:8px;padding:20px'
        card.innerHTML = html
        ov.appendChild(card)
        ov.onmousedown = function (e) { if (e.target === ov) close() }
        function close() { ov.remove() }
        // inside .v-application, so Vuetify utility classes apply
        ;(document.querySelector('.v-application') || document.body).appendChild(ov)
        return { el: card, close: close }
    }

    /* ---------------- lane info ---------------- */
    // A unit's lanes in slot order (AFC_lane "lane" is the 1-based slot)
    function unitLanes(u) {
        return ((u.status && u.status.lanes) || [])
            .map(function (n) { return lanes[n] })
            .filter(Boolean)
            .sort(function (a, b) { return a.lane - b.lane })
    }
    // The ACE's own slot report for a lane: RFID type/color/sku, empty or not
    function slotOf(u, l) {
        var slots = (u.status && u.status.ace && u.status.ace.slots) || []
        return slots[l.lane - 1] || null
    }
    function laneInfo(u, l) {
        var s = slotOf(u, l)
        var color = /^#?[0-9a-fA-F]{6}$/.test(l.color || '')
            ? '#' + l.color.replace('#', '') : ''
        return {
            present: !!l.prep,
            tagged: !!(s && s.type),
            type: l.material || '',
            color: color,
            sku: (s && s.sku) || '',
            map: Array.isArray(l.map) ? l.map.join(',') : (l.map || ''),
        }
    }

    /* ---------------- status refresh ---------------- */
    function query(ctx) {
        var q = ['AFC', 'print_stats'].concat(unitObjs, laneObjs)
            .map(encodeURIComponent).join('&')
        return ctx.apiGet('/printer/objects/query?' + q).then(function (r) {
            var st = r.result.status || {}
            units = unitObjs.map(function (o) {
                return { name: o.split(' ')[1], status: st[o] || {} }
            })
            lanes = {}
            laneObjs.forEach(function (o) {
                if (st[o] && st[o].name) lanes[st[o].name] = st[o]
            })
            cur = (st.AFC || {}).current_load || null
            printing = ['printing', 'paused'].indexOf((st.print_stats || {}).state) >= 0
            err = ''
        }).catch(function (e) { err = e.message || String(e) })
    }

    var lastRender = ''
    function refresh(ctx, force) {
        return query(ctx).then(function () {
            var s = JSON.stringify([units, lanes, cur, printing, err])
            if (force || s !== lastRender) {
                lastRender = s
                renderFn && renderFn()
            }
        })
    }

    /* ---------------- spool svg ---------------- */
    function spoolSvg(color) {
        if (!color)
            return '<svg viewBox="0 0 48 48" class="afcace-spool">' +
                '<circle cx="24" cy="24" r="19" fill="none" ' +
                'stroke="rgba(128,128,128,.4)" stroke-width="2" stroke-dasharray="5 4"/>' +
                '<circle cx="24" cy="24" r="7" fill="none" ' +
                'stroke="rgba(128,128,128,.4)" stroke-width="2"/></svg>'
        return '<svg viewBox="0 0 48 48" class="afcace-spool">' +
            '<circle cx="24" cy="24" r="20" fill="' + color + '"/>' +
            '<circle cx="24" cy="24" r="20" fill="none" stroke="rgba(0,0,0,.25)" stroke-width="1.5"/>' +
            // winding hint
            '<circle cx="24" cy="24" r="15" fill="none" stroke="rgba(0,0,0,.12)" stroke-width="1"/>' +
            '<circle cx="24" cy="24" r="11" fill="none" stroke="rgba(0,0,0,.12)" stroke-width="1"/>' +
            // hub
            '<circle cx="24" cy="24" r="7.5" fill="rgba(0,0,0,.45)"/>' +
            '<circle cx="24" cy="24" r="3.5" fill="rgba(255,255,255,.25)"/></svg>'
    }

    /* ---------------- lane editor (color wheel + material) ---------------- */
    function laneModal(ctx, u, l) {
        var info = laneInfo(u, l)
        var color = info.color || '#808080'
        var type = info.type || 'PLA'
        var hsv = hex2hsv(color)
        var m = openModal(
            '<div class="d-flex align-center mb-3" style="gap:12px">' +
            spoolSvg(color).replace('class="afcace-spool"',
                'data-preview style="width:42px;height:42px;flex:0 0 auto"') +
            '<div><div style="font-size:1.05rem;font-weight:500">' + esc(l.name) +
            (info.map ? ' · ' + esc(info.map) : '') + '</div>' +
            '<div style="opacity:.6;font-size:.78rem" data-hex>' + color +
            (info.sku ? ' · ' + esc(info.sku) : '') + '</div></div></div>' +
            (info.tagged
                ? '<p style="opacity:.65;font-size:.8rem;margin-bottom:12px">' +
                  'RFID spool — color and material come from the tag and ' +
                  'can’t be edited here.</p>'
                : '<div style="opacity:.6;font-size:.75rem;margin-bottom:6px">COLOR</div>' +
                  '<div style="position:relative;margin-bottom:10px">' +
                  '<div data-sq style="height:140px;border-radius:6px;cursor:crosshair"></div>' +
                  '<div data-sqmark style="position:absolute;width:12px;height:12px;' +
                  'border:2px solid #fff;border-radius:50%;pointer-events:none;' +
                  'box-shadow:0 0 3px rgba(0,0,0,.8);transform:translate(-50%,-50%)"></div>' +
                  '</div>' +
                  '<div style="position:relative;margin-bottom:10px">' +
                  '<div data-hue style="height:14px;border-radius:7px;cursor:crosshair;' +
                  'background:linear-gradient(to right,#f00,#ff0,#0f0,#0ff,#00f,#f0f,#f00)"></div>' +
                  '<div data-huemark style="position:absolute;top:50%;width:14px;height:14px;' +
                  'border:2px solid #fff;border-radius:50%;pointer-events:none;' +
                  'box-shadow:0 0 3px rgba(0,0,0,.8);transform:translate(-50%,-50%)"></div>' +
                  '</div>' +
                  '<div class="d-flex" style="gap:6px;margin-bottom:14px">' +
                  ['#f44336', '#4caf50', '#2196f3', '#ffeb3b', '#000000', '#ffffff']
                      .map(function (c) {
                          return '<button data-preset="' + c + '" style="flex:1;height:24px;' +
                              'border-radius:4px;border:1px solid rgba(128,128,128,.4);' +
                              'background:' + c + ';cursor:pointer"></button>'
                      }).join('') + '</div>') +
            (info.tagged ? '' :
                '<div style="opacity:.6;font-size:.75rem;margin-bottom:6px">MATERIAL</div>' +
                '<div class="d-flex" style="flex-wrap:wrap;gap:6px;margin-bottom:18px">' +
                ACE_TYPES.map(function (t) {
                    return '<button data-type="' + t + '" class="afcace-mchip' +
                        (t === type ? ' sel' : '') + '">' + t + '</button>'
                }).join('') + '</div>') +
            '<div class="d-flex" style="gap:8px">' +
            (info.tagged ? '' :
                '<button data-save class="v-btn v-btn--outlined v-size--small primary--text">Save</button>') +
            '<span style="flex:1"></span>' +
            '<button data-close class="v-btn v-btn--text v-size--small">Cancel</button>' +
            '</div>'
        )

        var hexLbl = m.el.querySelector('[data-hex]')
        var preview = m.el.querySelector('[data-preview]')
        function applyPreview() {
            color = hsv2hex(hsv.h, hsv.s, hsv.v)
            hexLbl.textContent = color + (info.sku ? ' · ' + info.sku : '')
            var circles = preview.querySelectorAll('circle')
            if (circles.length > 1) circles[0].setAttribute('fill', color)
        }

        var sq = m.el.querySelector('[data-sq]')
        if (sq) {
            var sqMark = m.el.querySelector('[data-sqmark]')
            var hue = m.el.querySelector('[data-hue]')
            var hueMark = m.el.querySelector('[data-huemark]')
            // saturation left->right, brightness top->bottom, for the hue
            function paint() {
                sq.style.background =
                    'linear-gradient(to top, #000, transparent), ' +
                    'linear-gradient(to right, #fff, ' + hsv2hex(hsv.h, 1, 1) + ')'
                sqMark.style.left = hsv.s * 100 + '%'
                sqMark.style.top = (1 - hsv.v) * 100 + '%'
                sqMark.style.background = hsv2hex(hsv.h, hsv.s, hsv.v)
                hueMark.style.left = (hsv.h / 360) * 100 + '%'
                hueMark.style.background = hsv2hex(hsv.h, 1, 1)
            }
            paint()
            function drag(el, fn) {
                el.onpointerdown = function (e) {
                    try { el.setPointerCapture(e.pointerId) } catch (x) { /* ok */ }
                    fn(e)
                    el.onpointermove = fn
                }
                el.onpointerup = function () { el.onpointermove = null }
            }
            drag(sq, function (e) {
                var r = sq.getBoundingClientRect()
                hsv.s = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
                hsv.v = Math.min(1, Math.max(0, 1 - (e.clientY - r.top) / r.height))
                paint()
                applyPreview()
            })
            drag(hue, function (e) {
                var r = hue.getBoundingClientRect()
                hsv.h = Math.min(359.9, Math.max(0,
                    (e.clientX - r.left) / r.width * 360))
                paint()
                applyPreview()
            })
            m.el.querySelectorAll('[data-preset]').forEach(function (b) {
                b.onclick = function () {
                    hsv = hex2hsv(b.dataset.preset)
                    paint()
                    applyPreview()
                }
            })
        }

        m.el.querySelectorAll('[data-type]').forEach(function (b) {
            b.onclick = function () {
                type = b.dataset.type
                m.el.querySelectorAll('[data-type]').forEach(function (x) {
                    x.classList.toggle('sel', x === b)
                })
            }
        })
        var save = m.el.querySelector('[data-save]')
        if (save) save.onclick = function () {
            ctx.gcode('SET_COLOR LANE=' + l.name + ' COLOR=' +
                color.replace('#', '').toUpperCase() + '\n' +
                'SET_MATERIAL LANE=' + l.name + ' MATERIAL=' + type)
                .catch(function () {})
                .then(function () { refresh(ctx) })
            m.close()
        }
        m.el.querySelector('[data-close]').onclick = m.close
    }

    /* ---------------- panel ---------------- */
    window.CosmosPanels.register({
        id: 'afc-ace',
        title: 'ACE Pro',
        replaces: ['afc'],
        // mdi-view-grid: four squares, one per slot
        icon: 'M3,11H11V3H3M3,21H11V13H3M13,21H21V13H13M13,3V11H21V3',
        buttons: [
            {
                // mdi-refresh
                icon: 'M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z',
                onClick: function (ctx) { refresh(ctx, true) },
            },
            {
                // mdi-dots-vertical
                icon: 'M12,16A2,2 0 0,1 14,18A2,2 0 0,1 12,20A2,2 0 0,1 10,18A2,2 0 0,1 12,16M12,10A2,2 0 0,1 14,12A2,2 0 0,1 12,14A2,2 0 0,1 10,12A2,2 0 0,1 12,10M12,4A2,2 0 0,1 14,6A2,2 0 0,1 12,8A2,2 0 0,1 10,6A2,2 0 0,1 12,4Z',
                menu: function (el, ctx) {
                    var b = document.createElement('button')
                    b.className = 'v-btn v-btn--text v-size--small'
                    b.textContent = 'Copy lanes for Orca'
                    b.onclick = function () {
                        var txt = []
                        units.forEach(function (u) {
                            unitLanes(u).forEach(function (l) {
                                var info = laneInfo(u, l)
                                txt.push((info.map || l.name) + ': ' +
                                    (info.color || '#000000') + ' ' +
                                    (info.present && info.type ? info.type : 'empty'))
                            })
                        })
                        navigator.clipboard && navigator.clipboard.writeText(txt.join('\n'))
                    }
                    el.appendChild(b)
                },
            },
        ],
        mount: function (el, ctx) {
            el.innerHTML =
                '<style>' +
                '.afcace-slots{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:4px 0 12px}' +
                '.afcace-slot{display:flex;flex-direction:column;align-items:center;gap:4px;' +
                'padding:12px 4px 9px;background:rgba(128,128,128,.06);' +
                'border:1px solid rgba(128,128,128,.18);border-radius:8px;' +
                'cursor:pointer;font-size:.76rem;transition:background .15s,border-color .15s}' +
                '.afcace-slot:hover{background:rgba(128,128,128,.14)}' +
                '.afcace-slot.active{border-color:var(--v-primary-base,#2196f3)}' +
                '.afcace-spool{width:40px;height:40px}' +
                '.afcace-chip{padding:1px 10px;border-radius:10px;font-size:.72rem;' +
                'background:rgba(128,128,128,.2)}' +
                '.afcace-chip.ok{background:rgba(76,175,80,.25)}' +
                '.afcace-chip.print{background:rgba(33,150,243,.25)}' +
                '.afcace-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}' +
                '.afcace-dryer{border-top:1px solid rgba(128,128,128,.18);' +
                'padding-top:10px;margin-top:2px}' +
                '.afcace-dryer+.afcace-dryer{margin-top:12px}' +
                '.afcace-dtitle{font-size:.82rem;margin-bottom:8px}' +
                '.afcace-dtitle b{font-weight:500}' +
                '.afcace-btn{padding:3px 10px;font-size:.72rem;border-radius:4px;' +
                'border:1px solid rgba(128,128,128,.35);background:transparent;' +
                'color:inherit;cursor:pointer;transition:background .15s}' +
                '.afcace-btn:hover:not(:disabled){background:rgba(128,128,128,.15)}' +
                '.afcace-btn:disabled{opacity:.4;cursor:default}' +
                '.afcace-field{display:inline-flex;align-items:center;gap:4px;' +
                'border:1px solid rgba(128,128,128,.35);border-radius:4px;padding:3px 8px}' +
                '.afcace-field input{width:34px;border:none;outline:none;' +
                'background:transparent;color:inherit;font-size:.74rem;' +
                'text-align:right;-moz-appearance:textfield;appearance:textfield}' +
                '.afcace-field input::-webkit-outer-spin-button,' +
                '.afcace-field input::-webkit-inner-spin-button' +
                '{-webkit-appearance:none;margin:0}' +
                '.afcace-field span{opacity:.6;font-size:.7rem}' +
                '.afcace-mchip{padding:3px 10px;font-size:.74rem;border-radius:12px;' +
                'border:1px solid rgba(128,128,128,.35);background:transparent;' +
                'color:inherit;cursor:pointer}' +
                '.afcace-mchip.sel{border-color:var(--v-primary-base,#2196f3);' +
                'color:var(--v-primary-base,#2196f3)}' +
                '.afcace-mchip:disabled{opacity:.45;cursor:default}' +
                '.afcace-note{opacity:.6;font-size:.78rem;margin:2px 0 8px}' +
                '.afcace-unitlbl{opacity:.55;font-size:.7rem;letter-spacing:.08em;' +
                'text-transform:uppercase;margin:6px 0 2px}' +
                '.afcace-tgl{position:relative;width:34px;height:18px;flex:0 0 auto;' +
                'border-radius:9px;background:rgba(128,128,128,.35);cursor:pointer;' +
                'border:none;padding:0;transition:background .2s}' +
                '.afcace-tgl:after{content:"";position:absolute;top:2px;left:2px;' +
                'width:14px;height:14px;border-radius:50%;background:#fff;transition:left .2s}' +
                '.afcace-tgl.on{background:var(--v-primary-base,#2196f3)}' +
                '.afcace-tgl.on:after{left:18px}' +
                '.afcace-tgl:disabled{opacity:.4;cursor:default}' +
                '</style>' +
                '<div data-body><p class="afcace-note">Loading…</p></div>'
            var body = el.querySelector('[data-body]')

            renderFn = function () {
                var multi = units.length > 1
                var u, i

                // keep user-typed custom values across re-renders (per unit)
                var vals = units.map(function (x, k) {
                    var pT = body.querySelector('[data-ct="' + k + '"]')
                    var pM = body.querySelector('[data-cm="' + k + '"]')
                    return {
                        t: pT && pT.value ? pT.value : dryDefaults.t,
                        m: pM && pM.value ? pM.value : dryDefaults.m,
                    }
                })

                var anyOnline = units.some(function (x) { return x.status.connected })
                var chip = printing
                    ? '<span class="afcace-chip print">printing</span>'
                    : '<span class="afcace-chip ' + (anyOnline ? 'ok' : '') + '">' +
                      (anyOnline ? 'ready' : 'offline') + '</span>'
                var html =
                    '<div class="afcace-row" style="margin-bottom:6px">' + chip +
                    (cur ? '<span class="afcace-note" style="margin:0">active: ' + esc(cur) + '</span>' : '') +
                    '</div>' +
                    (err ? '<p class="afcace-note">' + esc(err) + '</p>' : '')

                for (u = 0; u < units.length; u++) {
                    var unit = units[u]
                    if (multi)
                        html += '<div class="afcace-unitlbl">' + esc(unit.name) +
                            (unit.status.connected ? '' : ' — offline') + '</div>'
                    html += '<div class="afcace-slots">'
                    var ls = unitLanes(unit)
                    for (i = 0; i < ls.length; i++) {
                        var info = laneInfo(unit, ls[i])
                        var shown = info.present ? info : { color: '', type: '', tagged: false }
                        html += '<div class="afcace-slot' +
                            (cur === ls[i].name ? ' active' : '') +
                            '" data-unit="' + u + '" data-lane="' + esc(ls[i].name) +
                            '" title="' + esc(ls[i].name) + (info.map ? ' (' + esc(info.map) + ')' : '') +
                            ' — click to edit">' +
                            spoolSvg(shown.color) +
                            '<span>' + esc(shown.type || '—') + (shown.tagged ? ' ⦿' : '') + '</span>' +
                            '</div>'
                    }
                    html += '</div>'
                }

                for (u = 0; u < units.length; u++) {
                    var a = units[u].status.ace || null
                    var dryer = (a && a.dryer) || {}
                    var drying = String(dryer.status || '').toLowerCase() === 'drying'
                    var lock = !a || !units[u].status.connected
                    html +=
                        '<div class="afcace-dryer">' +
                        '<div class="afcace-dtitle">' +
                        (multi ? esc(units[u].name) + ' dryer ' : 'Dryer ') +
                        (drying
                            ? '<b>' + esc(dryer.target_temp) + '°C</b>/<b>' +
                              (a && a.temp != null ? esc(a.temp) : '–') +
                              '°C</b> — ' + fmtRemain(dryer.remain_time)
                            : '— off') + '</div>' +
                        '<div class="afcace-row">' +
                        '<span style="font-size:.78rem">Drying</span>' +
                        '<label class="afcace-field"><input data-ct="' + u + '" type="number" ' +
                        'min="35" max="65" value="' + vals[u].t + '"' +
                        (drying ? ' disabled' : '') + '><span>°C</span></label>' +
                        '<label class="afcace-field"><input data-cm="' + u + '" type="number" ' +
                        'min="10" max="1440" value="' + vals[u].m + '"' +
                        (drying ? ' disabled' : '') + '><span>min</span></label>' +
                        '<button data-drytgl="' + u + '" class="afcace-tgl' + (drying ? ' on' : '') + '"' +
                        (lock ? ' disabled' : '') + ' title="' +
                        (drying ? 'Stop drying' : 'Start drying') + '"></button>' +
                        '</div></div>'
                }
                body.innerHTML = html

                body.querySelectorAll('[data-lane]').forEach(function (d) {
                    d.onclick = function () {
                        var unit = units[+d.dataset.unit]
                        var l = lanes[d.dataset.lane]
                        if (unit && l) laneModal(ctx, unit, l)
                    }
                })
                body.querySelectorAll('[data-drytgl]').forEach(function (tgl) {
                    tgl.onclick = function () {
                        var unit = units[+tgl.dataset.drytgl]
                        var td = (unit.status.ace && unit.status.ace.dryer) || {}
                        var cmd
                        if (String(td.status || '').toLowerCase() === 'drying') {
                            cmd = 'AFC_ACE_DRYER_STOP UNIT=' + unit.name
                        } else {
                            var k = tgl.dataset.drytgl
                            var t = parseFloat(body.querySelector('[data-ct="' + k + '"]').value) || dryDefaults.t
                            var m2 = parseFloat(body.querySelector('[data-cm="' + k + '"]').value) || dryDefaults.m
                            cmd = 'AFC_ACE_DRYER_START UNIT=' + unit.name +
                                ' TEMP=' + Math.round(Math.min(65, Math.max(35, t))) +
                                ' DURATION=' + Math.round(Math.min(1440, Math.max(10, m2)))
                        }
                        ctx.gcode(cmd).catch(function () {})
                            .then(function () { refresh(ctx, true) })
                        tgl.classList.toggle('on')
                        tgl.disabled = true
                    }
                })
            }

            // The driver loaded? (guards against a stale panel file)
            function boot() {
                ctx.apiGet('/printer/objects/list').then(function (r) {
                    var objs = r.result.objects || []
                    unitObjs = objs.filter(function (o) { return o.indexOf('AFC_ACE ') === 0 })
                    laneObjs = objs.filter(function (o) { return o.indexOf('AFC_lane ') === 0 })
                    if (!unitObjs.length) {
                        body.innerHTML =
                            '<p class="afcace-note">No ACE unit loaded — install the ' +
                            'cosmoace_afc driver and include its config.</p>'
                        renderFn = null
                        return
                    }
                    refresh(ctx, true)
                    pollTimer = setInterval(function () { refresh(ctx) }, POLL_MS)
                }).catch(function () {
                    // klippy still starting — retry while the panel is on screen
                    body.innerHTML =
                        '<p class="afcace-note">Printer not ready — retrying…</p>'
                    if (el.isConnected) setTimeout(boot, 5000)
                })
            }
            boot()
        },
        unmount: function () {
            renderFn = null
            if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        },
    })
})()
