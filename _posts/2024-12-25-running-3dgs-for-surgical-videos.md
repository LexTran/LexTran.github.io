---
layout: post
title: Running 3DGS for surgical videos
date: 2024-12-25
tags: [3dgs]
---

# Git clone
The first thing about using 3D Gaussian Splatting (3DGS) is that you should always remember 3DGS is actually a complex and large repo to clone. So it is most likely you will encounter an error says "error: 2278 bytes of body are still expected fetch-pack: unexpected disconnect while reading sideband packet fatal: early EOF fatal: fetch-pack: invalid index-pack output". If you do encounter it, don't panic. Try following method:
1. We need to reset the buffer: git config --global postBuffer 2G
2. Shallow clone the repo: git clone <repo address> -depth=1
3. Git fetch the rest part: git fetch --unshallow

This should work, if not, you may need to check out your internet configuration and local storage situation.

# Environments
Another big problem is that you need to install dependencies not only for 3DGS but also for its submodules (diff-rasterizer & simple-knn). Now, the dependencies of simple-knn are easy to install, but you may encounter errors when installing packages for diff-rasterizer. If so, checkout the detailed messages since you may miss some cpp libraries. In my case, libglm-dev is missing.

# Running
So far, all the preparation work is done. You can run the demo program now! For those who have never contact 3D reconstruction before (just like me), you should know that the training of 3D reconstruction is to train the model to reconstruct 3D models (.ply in 3DGS cases). Apparently, a .ply data cannot be direcly seen, you have to send it into a professional 3D model software (Blender e.g.). But, you do can render the 3D model into 2D pictures and hence see the results.

