# Stock Locations

todo: add more information to define how the Inventree locations will be set up.

## Locations with LED indictor

Some locations (Shelves) will be set up with indicators to aid in finding the parts that are being packaged or kitted.

Typical WS2814A LED strings that operate from 12V, see Amazon [B0B9S3XFJB](https://www.amazon.com/BTF-LIGHTING-Addressable-20Pixels-100pixel-Flexible/dp/B0B9S3XFJB), have three LEDs in a string per WS2814A chip. Three LEDs will light with the same color since they are driven with a single WS2814A, they are spaced at 60 LED per meter so 0.05 meters (~ 2 in) will light with the same color. My shelf is 1.1 meters wide so if I consider each 0.05 meters as a storage bin I can light up each to help locate items as I am kitting for productioin runs.
