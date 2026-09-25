set -e
nix --extra-experimental-features "nix-command flakes" \
        --option sandbox false \
        build /src#image -o /tmp/image
if [ -f /tmp/image/image.tar.gz ]; then
    cp /tmp/image/image.tar.gz /out/image.tar.gz
else
    cp -L /tmp/image /out/image.tar.gz
fi
