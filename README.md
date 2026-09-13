# Balanced Photo Mosaic

A tool for generating photo mosaics — images recreated by arranging many smaller tile images — using a balanced tile usage strategy. 

Unlike traditional mosaics that select the closest color match for each tile and can overuse similar tiles in large uniform regions, this approach distributes tiles more evenly across the mosaic while still color-matching each placement to the target image. The result is mosaics with better variety and reduced repetitiveness, even with limited or color-biased tile sets.

## Installation

    pip install pillow numpy
    
## Usage

    python photomosaic.py target.jpg tiles_folder

or 
    
    python photomosaic.py target.jpg tiles_folder --tile-size 50 --enlargement 8 --mode meanstd --seed 123 --out mosaic.jpeg

## Example

Here is my octocat (from https://myoctocat.com/)

<p align="center">
<img src="https://github.com/jiahaozhang2025/photo-mosaic/blob/main/images/octocat.png" width="500"/>
</p>

Here is the comparison of the mosaic built from a dataset of emojis. Which is better is of course a matter of personal taste, personally I do not want my octocat face to be made of emojis of poopies and aliens. 

Interestingly, in `meanstd` mode, emojis show up primarily along the contour, hence highlighting the features in the target image. You can check the detailed implementation in the code, but basically: in chromatically uniform regions the color variation is low -> the ratio of target std over emoji std is low -> this ratio sets how much the original contrast of the emoji is preserved -> so the contrast of emoji tile is suppressed and blent into background.

| Target | Conventional Approach |
|:------:|:--------------:|
| <img src="https://github.com/jiahaozhang2025/photo-mosaic/blob/main/images/octocat_zoom.png" width="400"/> | <img src="https://github.com/jiahaozhang2025/photo-mosaic/blob/main/images/mosaic_zoom_conventional.jpeg" width="400"/> |

| This Approach (mean mode) | This Approach (meanstd mode) |
|:------:|:--------------:|
| <img src="https://github.com/jiahaozhang2025/photo-mosaic/blob/main/images/mosaic_zoom_mean.jpeg" width="400"/> | <img src="https://github.com/jiahaozhang2025/photo-mosaic/blob/main/images/mosaic_zoom_meanstd.jpeg" width="400"/> |

# Acknowledgements

Inspired by the classic best-fit photomosaic approach by codebox: 
https://github.com/codebox/mosaic.git


