set -e
nix --extra-experimental-features "nix-command flakes" \
        --option sandbox false \
        eval --raw --impure --expr 'import /src/check-extra-packages.nix' \
        > /out/extra-packages-check.json
