- Most important thing right now I feel like is getting the data in. So we need to collect from different data sources to get a high detail satellite + category images whichI can easily import into blender.



- Make a deeper analysis of what the other MILITARY-SIMS are doing and how they are doing, but also try to critizie their work and the possible "problem zones" they face
	-  [Digital Imaging and Remote Sensing Image Generation | Digital Imaging and Remote Sensing Laboratory (DIRS) | RIT](https://www.rit.edu/dirs/dirsig) looks really really promising for example. THey also talk about how they process the data, how they visualize it and I think that might be quite useful to understand to know how to do it correctly
- The noise implementation is really lack luster at the moment. I think we need to detial this further, at the moment it's just a collection of different effects
- IN  genereal all the nodes are quite "high level" of writing meaning it's hard to follow sometimes as I am not a expert in this field. We need to adjust the language and "knowledge"-base a bit more "bachelor level" so I can start to understand
- A entry file which is slowly leading me through the knowledge base build might be important
- A strong focus on Unreal Engine which I already told you, I think we have to archieve it
- In general the folder has to be a bit more "sorted" into different categeroies even isnide teh concept folder as it is hard to read. Then we can leave some of the "overview" files above which actually read a bit like papers taking you from start to finish. If I wanna deepen something I can then just click the "source-node" which will explain the specific paper in depth. [[plan-wiki-cleanup]]  already details this I think now that I look at it. But it has not been executed yet
	- I just noticed that a part of the prompt has been fullfilled? nOt sure....
- I am missing general scene generation setup help also: I mean I can see where you are describing textures for infrared, but at the same time we also need the underlying scenery data to generate larger scenes or maybe I just overread that
- Blender GIS:
	- **Goal:** Streamline the process of getting the satelite images, height data, and OSM files from the internet downloaded. Then use the files and import them using BLender GIS into blender with a scale that makes sense. (Facing the issue for example that the clipping or something is off and I can'T really see the buildings and stuff on a biger scale? Is blender even the best tool for such large scales.. what do I have to modify that I can use it for viewport rendering of big scale and then also obviously for the rendering itself) 
	- The main issue right now with the importing is that I have no internet access and have to get the images and data from the openMap-Unifier. So basically I am using our proxy there to get the files in and then import them onto my laptop, then to my Virtual Machine where my Blender Project is housed. THere I have to import the satelite images and so on. This is where the problem starts, the satelite images can be imported, but only one by one. If I select all of them at once it just imports one of them. Am I doing something wrong here?
	- In General I feel like I want to just use the openmap-unifier to get data from the mapping places (e.g openstreetmap and opendatabayern) onto my laptop  and push it right through onto my virtual machine with ssh or filezilla or whateer the fuck I can use to get it through lol
I tried some scripts:
```` python
import bpy
import os

# assign directory
directory = 'afolder/'
 
# iterate over files in that directory
for filename in os.listdir(directory):
    f = os.path.join(directory, filename)
    # checking if it is a file
    bpy.ops.importgis.georaster(filepath=f)
````
ERROR I GET: 
````
           ^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\xxx\AppData\Roaming\Blender Foundation\Blender\5.0\scripts\addons\BlenderGIS-master\operators\utils\georaster_utils.py", line 223, in __init__
    GeoRaster.__init__(self, path, subBoxGeo=subBoxGeo, useGDAL=useGDAL)
  File "C:\Users\xxx\AppData\Roaming\Blender Foundation\Blender\5.0\scripts\addons\BlenderGIS-master\core\georaster\georaster.py", line 90, in __init__
    raise IOError("Unable to read georef infos from worldfile or geotiff tags")
OSError: Unable to read georef infos from worldfile or geotiff tags
WARNING:BlenderGIS-master.core.georaster.georaster:145:Cannot extract georefencing informations from tif tags
ERROR:BlenderGIS-master.operators.io_import_georaster:259:Unable to open raster
Traceback (most recent call last):
  File "C:\Users\xxx\AppData\Roaming\Blender Foundation\Blender\5.0\scripts\addons\BlenderGIS-master\operators\io_import_georaster.py", line 257, in execute
    rast = bpyGeoRaster(filePath)
           ^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\xxx\AppData\Roaming\Blender Foundation\Blender\5.0\scripts\addons\BlenderGIS-master\operators\utils\georaster_utils.py", line 223, in __init__
    GeoRaster.__init__(self, path, subBoxGeo=subBoxGeo, useGDAL=useGDAL)
  File "C:\Users\xxx\AppData\Roaming\Blender Foundation\Blender\5.0\scripts\addons\BlenderGIS-master\core\georaster\georaster.py", line 90, in __init__
    raise IOError("Unable to read georef infos from worldfile or geotiff tags")
OSError: Unable to read georef infos from worldfile or geotiff tags
````


Interesting read: [Blackshark.ai - AI Infrastructure for the Physical World](https://www.blackshark.ai/#applications)

--> This oen questions about what kind of database we can actually get online as we are using opendatabayern and openstreetmap at the moment




- The OpenMap-Unifier has the issue that it is not saving the proxy host and username and other options I set before. password should obviously not be saved, which it doesnt. Hence I would porpose that you do changes on that level too please.
	-  A clear folder option might be useful
	- A overview over what maps we downloaded and a handy overview map wise what data we just downloaded might be useful too
	- Careful though, that the proxy is a bit difficult sometimes and hence intial starts might not work until you install

For now I noticed the openbayern database has relief. But I don't want relief but rather the height. So maybe you can scrap what openbayern has database wise and then try to get all the ways to download those categories and then make a nice, usability one

WE need spficiations of license for openstreetmap and opendatabayern:

````Open Data Commons Open Database License (ODbL) Summary

This is a human-readable summary of the [ODbL 1.0 license](https://opendatacommons.org/licenses/odbl/1-0/). Please see the disclaimer below.

You are free:

- _To share_: To copy, distribute and use the database.
- _To create_: To produce works from the database.
- _To adapt_: To modify, transform and build upon the database.

As long as you:

- _Attribute_: You must attribute any public use of the database, or works produced from the database, in the manner specified in the ODbL. For any use or redistribution of the database, or works produced from it, you must make clear to others the license of the database and keep intact any notices on the original database.
- _Share-Alike_: If you publicly use any adapted version of this database, or works produced from an adapted database, you must also offer that adapted database under the ODbL.
- _Keep open_: If you redistribute the database, or an adapted version of it, then you may use technological measures that restrict the work (such as DRM) as long as you also redistribute a version without such measures.

**Disclaimer**

This is not a license. It is simply a handy reference for understanding the [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) — it is a human-readable expression of some of its key terms. This document has no legal value, and its contents do not appear in the actual license. Read the [full ODbL 1.0 license text](https://opendatacommons.org/licenses/odbl/1-0/) for the exact terms that apply.
````
## OUTSIDE OF PROJECT
- I am still missing the time calculator which I can run from the start to track my times with the right booking numbers so I can properly track my times with some nice usability and time managamnet and pomodore technique (which is optional as in should be a extra I can activate and shouldn't be linked to the time tracking itself (as in stop tracking in breaks or os))
- Trian Summary would be fucking awesome. --> I provided scripts and documentation, we want to try to get some lua coding going 
- I would like to get a detailed setup guide for LLMs in general specifically the QWEN 3.5 27b model, what quantization, what model settings for what use case? How can we quickly change those around? Are there optmization stuff. 
	- I would like to collect more models LLM so we can seperate coding and general use tasks or search taks productively (Maybe a decision model which points to the complexity of the task so the right model is being used, but also the way to use a speciific model)
	- Sometimes i do the code documentation use case as in ( lcforge) and I am wondering what my settings should be for that. 
	- Adding multi-modality like Whisper.cpp or other open source models to help with transcribing and stuff along those lines (Which models are useful for that? How do the whisper.cpp models compare to multi-modal models like gemma 4 4b (or was it another one, but yeah smoething laong thse lines))