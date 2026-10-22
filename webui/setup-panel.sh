#!/bin/sh
# Install or remove the optional "ACE Pro" Mainsail panel.
#
#   setup-panel.sh install   add the panel (and the bundled loader on COSMOS
#                            builds without the Mainsail Panel Extender)
#   setup-panel.sh remove    take it out; Mainsail goes back to stock
#
# Mainsail's own AFC panel is untouched either way. Runs over SSH, or from
# Mainsail with AFC_ACE_PANEL ACTION=INSTALL|REMOVE.

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ADD=/user-resource/webui-addons
PANEL="$ADD/panels/afc-ace"
INIT=/etc/init.d/afc-ace-webui
MARK="$ADD/.afc-ace-bundled-loader"

case "$1" in
    install)
        if [ ! -d /var/www/mainsail ]; then
            echo "Mainsail not found; nothing installed."
            exit 1
        fi
        mkdir -p "$PANEL"
        cp "$HERE/panel.js" "$PANEL/panel.js"
        chmod 0644 "$PANEL/panel.js"
        if [ -f /var/www/addons/loader.js ]; then
            echo "Panel installed (COSMOS ships the Mainsail Panel Extender)."
        else
            cp "$HERE/loader.js" "$ADD/loader.js"
            chmod 0644 "$ADD/loader.js"
            touch "$MARK"
            sed 's/\r$//' "$HERE/afc-ace-webui.init" > "$INIT"
            chmod 0755 "$INIT"
            for rl in 2 3 4 5; do
                [ -d "/etc/rc${rl}.d" ] && ln -sf ../init.d/afc-ace-webui "/etc/rc${rl}.d/S97afc-ace-webui"
            done
            "$INIT" start
            echo "Panel installed (bundled loader)."
        fi
        echo "Reload Mainsail, then turn the panel on in Settings > Dashboard."
        ;;
    remove)
        rm -rf "$PANEL"
        # The bundled loader goes only if we put it there and no other
        # addon panel still needs it; a native extender is never touched.
        if [ -f "$MARK" ] && [ -z "$(ls -d "$ADD"/panels/*/ 2>/dev/null)" ]; then
            [ -x "$INIT" ] && "$INIT" remove
            rm -f "$INIT" /etc/rc*.d/S*afc-ace-webui \
                  "$ADD/loader.js" "$ADD/manifest.json" "$MARK"
        elif [ -x "$INIT" ]; then
            "$INIT" start   # rewrite the manifest without our panel
        fi
        rmdir "$ADD/panels" "$ADD" 2>/dev/null || true
        echo "Panel removed. Reload Mainsail."
        ;;
    *)
        echo "Usage: $0 install|remove"
        exit 1
        ;;
esac
