# -*- coding: utf-8 -*-

#Created on Wed Aug 18 14:00:06 2021

#@author: jonat
# what does the following code look like in julia?

# WARNING
# WARNING: Do not run this file in a directory containing pdfs or pngs that you care about.
# Out of laziness, it just deletes all pdfs and pngs 
# LIBS_REQUIRED:
# * https://opencv.org/releases/
# * https://imagemagick.org/index.php
# * https://poppler.freedesktop.org/
# Also, required: a C/C++ compiler, e.g. https://clang.llvm.org/ 

import os # used for file operations on disk
import numpy as np #used for numpy arrays and for compat with plotting
import plotly.graph_objects as go #library used for 3d scatter plots
import requests # used to make calls to the web
from urllib.parse import urljoin # used to find and add .pdfs in a link
from bs4 import BeautifulSoup # used to parse and get information from a webpage -- in particular to find pdfs
from pdf2image import convert_from_path #dumps a pdf into an image
from image_slicer import slice # used to slice an image into a grid
import cv2 #cpu-only computer vision package
import pandas as pd # for creating dataframes
from scipy.cluster.vq import kmeans,vq #for running kmeans and clustering respectively
import json #for converting dictionaries to json


url = "https://winnipeg.ca/waterandwaste/drainageFlooding/rainfallReports/default.stm" # the website with all the rain data



#Use the working directory in this script
folder_location = '.'


# In Winnipeg, there are many rainfall gauge stations, and we 
# define a rainevent to be the tuple consisting of the rainfall events at each station.  
# We will store the information in a JSON file where the JSON file is structured as a list of rainevents
# where a rain event is a key-value store consisting of the time-stamp or stamps which serves as our UID and key-value 
# pairs of the form station-name: rainfall-amount.

# The following function computes the dominant (averaged) colour in a png using k-means+elbow method
# Inputs:
# @png_name: the name of the png being analyzed
# Outputs: 
# @return: The dominant (averaged) colour in (r,g,b) form
def get_dominant_color(png_name):
    # load the image 
    image = cv2.imread(png_name)
    #openCV uses BGR, so we convert to RGB
    imageRGB = cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
    # split the image into r,g,b
    r=[]
    g=[]
    b=[]
    for row in imageRGB:
        for pixel in row:
            # we know (255,255,255) occurs only on the edge and (0,0,0) occurs only as the road color so we can drop those from analysis
            (pr,pg,pb) = (pixel[0],pixel[1],pixel[2])
            if (pr <=5 and pg <= 5 and pb <= 5) or (pr >= 250 and pg >= 250 and pb >= 250):
                continue #continue restarts the loops ignoring the rest of the code, thus we don't add close to all 255 nor close to all 0
            r.append(pixel[0])
            g.append(pixel[1])
            b.append(pixel[2])
    #now we have r,g,b data with edge and road/key colours removed.            
    #create a dataframe from the r,g,b data so that we can use kmeans
    #here we ensure that the datatypes are all uint8 so 0-255 so in the expected rgb space.  We acknowledge round-off error
    # arising from working with discretized data.
    df = pd.DataFrame({'red': pd.Series(r,dtype='uint8'), 'green':pd.Series(g,dtype='uint8'), 'blue':pd.Series(b,dtype='uint8')})
    
    #now apply the elbow method.  We are clustering around 5 colours, heuristically, we can inc. and dec. to make more accurate
    num_clusters=5
    #internally the kmeans requires we convert values to float.
    cluster_centers, distortion = kmeans(df[['red','green','blue']].values.astype(float), num_clusters)
    #create clusters to determine largest cluster
    #idx classifies each point in vq with a number 0--4 corresponding to which bin it is in (relative to the cluster centers)
    #  so if the nearest neighbor to a point is cluster_centers[i] then the point is listed as i in idx.
    idx,_ = vq(df,cluster_centers)
    #to get the size of the clusters, we use np.bincount
    cluster_sizes = np.bincount(idx)
    #finally we pull the largest size
    biggest_cluster = max(list(zip(cluster_centers,cluster_sizes)),key=lambda cen_siz: cen_siz[1])[0]
    #extract out the dominant color feature
    (rdom,gdom,bdom) = (biggest_cluster[0],biggest_cluster[1],biggest_cluster[2])
    
    #force a garbage collection of the large data structures, r,b b,df because we need to keep the memory usage down
    del r
    del g
    del b
    del df
    #finally, return the result 
    return (rdom,gdom,bdom)

#The following function adds a single rainevent
#to our listing of rainevents. We operate on the convention of how the image split library saves file names
#Our inputs are 
# @event_name: this is the name of the pdf file without the suffix pdf -- used to reference the pngs generated by 
#              splitting
# @stations: this is a tuple of numbers giving the "row" and "column" of the box in the grid that we want along with 
#            string that gives the station name @stations=(row,column,station_name)
#            recall that image split outputs pngs in the form mainImgName_rownum_colnum.png, so the row, column is sufficient
# @allowed_shift: amount of RGB drift allowed that keeps the error in mm under 0.1mm
# @colour_map: this is a function that describes how to convert a colour in the blue-red gradient into a rainfall amount
#              we expect this in practice to be approximate as it is reverse engineered by hand from the rain maps
#              We should write down here a bound on the error in the conversion (and strive to make this as low as possible)
# @events: this is a python dictionary that holds the rain-events so far.  Note that python dictionaries are 1-1 convertible 
#          to JSON, so we are operating on the desired JSON file here.
# There is no output to the function; however, there is a side-effect with a postcondition
# Side-effect: the variable @events is modified to contain the data point we need.
# Note this function is neither concurrent nor reentrant safe -- use as singlethreaded only, or impose locks to make safe
def add_event_worker(event_name,stations,allowed_shift,colour_map,events):
    #step1: load the correct pngs into memory -- each png correponds to a small region around a station
    png_names = []
    for file in os.listdir(folder_location):
        if file.endswith(".png"):
            png_names.append(file)
    #step1.a: filter the stations from the png_names -- to be done for now we just do the output for all squares.
    #but this would filter png_names to be smaller    
    
    #step2: create a blank dictionary to hold the single event
    new_event = dict()
    new_event["time_stamp"] = event_name
    rainfall_amounts = dict()
    
    #step3: for each png, calculate the average colour in the box, and apply the colour_map to get a rainfall amount
    for png_name in png_names:
        (r,g,b) = get_dominant_color(png_name)
        rainfall_amounts[png_name] = colour_map(r, g, b, allowed_shift)
    #step4: add the field to the dictionary
    new_event["rainfall_amounts"] = rainfall_amounts
    print(new_event)
    #step6: add the event to events and exit
    events.append(new_event)
    #done

# The following function is the main driver for adding an event.  It operates on a single pdf,
# opens the pdf, converts the pdf to a png, splits the png into some number of boxes, 
# calls add_event to actually add the event, and then cleans up all the pngs generated, as well as 
# deletes the pdf from the file system.  The inputs are
# @event_nam_with_suffix: the name of the pdf as on disk -- that is the file name with the suffix pdf.
# @colour_map: this is a function that describes how to convert a colour in the blue-red gradient into a rainfall amount
#              we expect this in practice to be approximate as it is reverse engineered by hand from the rain maps
#              We should write down here a bound on the error in the conversion (and strive to make this as low as possible)
# @events: this is a python dictionary that holds the rain-events so far.  Note that python dictionaries are 1-1 convertible 
#          to JSON, so we are operating on the desired JSON file here.
# @grid_links: the number of squares to subdivide the map into.  This needs to be a number of the form n^2 so that we can make a square grid
# @station_indices: this is a pair of numbers indicating the (row,column,name) of each station, together with the station name.
#                   in theory, this could be computed algorithmically from the map, using precise coordinates of the stations
#                   and the number of boxes to make.  However, this is not a general purpose library, so, I'm being lazy.
# @allowed_shift: amount of RGB drift allowed that keeps the error in mm under 0.1mm
# There is no output from this function, however there are multiple side-effects, two of which are observable.
# The side-effects are:
# $s1[observable]: a rain event is added to events as described by add_event_worker
# $s2[observable]: the pdf event_name_with_suffix is removed from hard drive
# $s3[un-observable]: a png corresponding to the event_name is created on disk and deleted before exiting
# $s4[un-observable]: grid_links many pngs are created -- one for each grid square -- on disk and deleted before exiting
def add_event_from_pdf(event_name_with_suffix,colour_map,events,grid_links,station_indices,allowed_shift):
    #step1: convert pdf to png 
    event_name_pure = event_name_with_suffix[:-4]# remove .pdf 
    event_name_png = event_name_pure + ".png"
    event_as_png = convert_from_path(event_name_with_suffix,720)[0]# get the converted image
    event_as_png.save(event_name_png,'PNG')
    
    #step2: split the png by grid_links
    slice(event_name_png,grid_links)# all the images event_name_pure_row_column.png are produced
    
    #step3: call add_event_worker on event_name-'.pdf,station_indices,colour_map,events to add the rain event to events
    add_event_worker(event_name_pure, station_indices, allowed_shift, colour_map, events)
    #step4: the pdf and delete all the pngs created in step1 and step2
    os.remove(event_name_with_suffix)
    for file in os.listdir(folder_location):
        if file.endswith(".png"):
            os.remove(file)
    #for profiling the run and making sure that we are progressing (and haven't run out of memory)
    print("events so far:")
    print(events)
    print("\n")
    #done

# The following function is the main driver for getting weather data.
# It processes every pdf obtained from the Winnipeg rainfall data and adds weather events to a dictionary, and then converts
# the dictionary to a JSON file, and returns the JSON
# Inputs are:
# @colour_map: this is a function that describes how to convert a colour in the blue-red gradient into a rainfall amount
#              we expect this in practice to be approximate as it is reverse engineered by hand from the rain maps
#              We should write down here a bound on the error in the conversion (and strive to make this as low as possible)
# @grid_links: the number of squares to subdivide the map into.  This needs to be a number of the form n^2 so that we can make a square grid
# @station_indices: this is a pair of numbers indicating the (row,column,name) of each station, together with the station name.
#                   in theory, this could be computed algorithmically from the map, using precise coordinates of the stations
#                   and the number of boxes to make.  However, this is not a general purpose library, so, I'm being lazy.
# @allowed_shift: amount of RGB drift allowed that keeps the error in mm under 0.1mm
# There is one output
# @rainy_json_dayta: The json file containing all the rain events
def add_all_events_from_pdf(colour_map,grid_links,station_indices,allowed_shift):
    #step1: load all pdf names generated by the beautiful soup html parser to a vector (this is just all pdf names in working directory)
    event_pdfs = []
    for file in os.listdir(folder_location):
        if file.endswith(".pdf") and not(file.__contains__("inten")):# if the file is a pdf and doesn't have intensity in the name.
            event_pdfs.append(os.path.join(folder_location,file)) 
    print(event_pdfs)# just used for monitoring
    #step2: create an empty events dictionary
    events = []
    #step3: for each pdf name generated by the pdf scrape in the main script, run add_event_from_pdf to add the event to events
    for event_pdf in event_pdfs:
        add_event_from_pdf(event_pdf,colour_to_rainfall_mm,events,grid_links,station_indices,allowed_shift)
    #step4: put a header in the dictionary, convert to JSON and return
    events_JSON = json.dumps({"events":events},indent=4)
    #step5: save the json to a file
    with open('rainfall_events.json','w') as outfile:
        json.dump({"events":events},outfile,indent=4)
    return events_JSON

# To create a colour map, we simply invert the gradient they used.  The gradient they used 
# is a piecewise (partial) linear curve in colour-space (aka RGB-space aka R_{>=0}^3)
#   The curve is [0,100] \to RGB and is broken down 
#   piecewise into the domains [0,25], [25,50], [50,100]
#   On the domain [0,25], we have the linear gradient from (0,144,255) to (0,255,0)  (blue-ish to green)
#   On the domain [25,50], we have the linear gradient from (0,255,0) to (255,255,0) (green to yellow)
#   On the domain [50,100], we have the linear gradient from (255,255,0) to (255,0,0) (yellow to red)
def gradient_curve(y):
    x = float(y) # yeah... try to convince me that types are annoying ...
    if 0 <= x <= 25:
        return (0,(1-x/25)*144 + x/25*255,(1-x/25)*255)
    elif 25 <= x <= 50:
        return (((x-25)/25)*255,255,0)
    elif 50 <= x <= 100:
        return (255,((x-50)/50)*255,0)
    else: 
        return (255,255,255)# this is technically undefined, we just return black all else
    
# To visualize the above curve... in colour space
# make a grid
# 0,1,2,...,100
# uncomment code below to display colour map
#ls = np.linspace(0,100,101)
# make the arrays for the r,g,b axes
#r,g,b = zip(*map(gradient_curve,ls))
# now make an array with the colours 
#colours = list(zip(r,g,b))
# create a 3d scatter plot with colours
# this creates a 3d plot with points corresponding to 0,1,...,100 and colours by the gradient
#fig=go.Figure(data=go.Scatter3d(x=r,y=g,z=b,marker=dict(size=4,color=colours),line=dict(color=colours,width=3)))
# create a figure of fixed size
#fig.update_layout(width=800, height=700,autosize=False)
# display the figure -- this should open the figure 
# in the webbrowser and be zoomable and twistable.  
# can be manually saved to hard drive from here.
# also, we have presaved the image
#fig.show()

#now we can invert the gradient curve.
# N.B. the 
# here we invert a color in RGB space to a point 
# between 0 and 100.  This allows us to reconstruct
# the rainfall amount from the color.  
# Of course, this isn't actually possible.  So what 
# we do is find the closest point in RGB space to one on the 
# line, and as long as the translation doesn't cause an error of more than 0.1 mm
# we don't worry.  If it does, we return a "rainfall" amount of -1 to denote an error
# So given a point, we use the definition of the gradient curve as above, 
# to find the closest point on the line to the given point, and then we simply invert
# the affine equation.
def colour_to_rainfall_mm(rval,gval,bval,allowed_shift):
    #step1: find shortest distance p to piece1 
    (x0,y0) = (gval,bval)#project onto green-blue plane
    (x_closest,y_closest) = get_point_min_dist((144,255),(255,0),(x0,y0))
    # in rgb space this is (0,x_closest,y_closest)
    d1squared = (y_closest-y0)**2 + (x_closest - x0)**2
    # p1,p2,p3 are the point back in rgb space with and indicator of which point they are and the distance
    p1 = ((0,x_closest,y_closest),1,d1squared)
    
    #step2: find shortest distance p to piece2
    (x1,y1)=(rval,gval)#project onto red-green plane, and distance is to the green to yellow shift (yellow is max red+max green)
    (x1_closest,y1_closest) = get_point_min_dist((0,255), (255,255), (x1,y1))
    #in rgb space this is (x1_closest,y1_closest,0)
    d2squared = (y1_closest-y1)**2 + (x1_closest-x1)**2
    p2 = ((x1_closest,y1_closest,0),2,d2squared)
    
    #step3: find shortest distance p to piece3
    (x2,y2) = (rval,gval)#again project onto red-green plane, distance is to red yellow shift
    (x2_closest,y2_closest) = get_point_min_dist((255,0), (255,255), (x2,y2))
    #in rgb space this is (x1_closest,y1_closest,0)
    d3squared = (y2_closest-y2)**2 + (x2_closest-x2)**2
    p3 = ((x2_closest,y2_closest,0),3,d3squared)
    
    #step4: select the point on line by the minimal distance over all note in python we can do min with a "key" which tells how to process points before comparison
    minp1p2 = min(p1,p2,key=lambda p: p[2])
    
    #note minoverall tells us the point on the line, which piece we are in, and the distance
    minoverall = min(minp1p2,p3,key=lambda q:q[2])
    ((rval_closest,gval_closest,bval_closest),piece_number,dsquared) = minoverall
    
    #step5: determine if the distance amounts to an error 
    #  of more than 0.1mm
    # ERROR: currently omitted
    
    #step6: if everything is good compute the rainfall amt and return or return -1 indicating failure    
    if piece_number == 1:
        return invert_piece1(rval_closest,gval_closest,bval_closest)
    elif piece_number == 2:
        return invert_piece2(rval_closest,gval_closest,bval_closest)
    elif piece_number == 3:
        return invert_piece3(rval_closest,gval_closest,bval_closest)
    else:
        return -10 # something really off would have to happen to trigger this -- consider -10 a bug
    
    


#piece1 is the blue-green shift.
#if in piece1 then note that bval = (1-(x/25))255 so x = 25(1-(bval/255))
# where x is the rainfall in mm
def invert_piece1(rval,gval,bval):
    return 25*(1-(bval/255))
#piece2 is the green-yellow shift
#if in piece2 then rval = ((x-25)/25)*255 so x=25*(rval/255)+25
def invert_piece2(rval,gval,bval):
    return 25*(rval/255)+25
#piece3 is the yellow-red shift
#if in piece3 then gval=((x-50)/50)*255 so x=50*(gval/255)+50
def invert_piece3(rval,gval,bval):
    return 50*(gval/255)+50

def get_point_min_dist(p1,p2,p):
    p1X,p1Y = p1
    p2X,p2Y = p2
    p1x = float(p1X)
    p1y = float(p1Y)
    p2x = float(p2X)
    p2y = float(p2Y)
    x00,y00 = p
    x0 = float(x00)
    y0 = float(y00)
    a = p1y-p2y
    b = p2x-p1x
    c = p1x*p2y - p2x*p1y
    x = (b*(b*x0-a*y0)-a*c)/(a*a + b*b)
    y = (a*((-1)*b*x0+a*y0)-b*c)/(a*a+b*b)
    return (x,y)

#for ease of use we hardcode in defaults for grid_links and station indices
default_grid_links = 64 # number of grid squares to create by default
default_station_indices = [] # a list of (row,col,name) corresponding to the row and column in the grid containing the station with name name
default_allowed_shift=1000#this parameter needs tuned to be accurate
# now we're all set to call add_all_events_from_pdf(colour_to_rainfall_mm,default_grid_links,default_station_indices) in the main script!  woohoo.

#response = requests.get(url)
#soup = BeautifulSoup(response.text,"html.parser")
#for link in soup.select("a[href$='.pdf']"):
#    filename = os.path.join(folder_location,link['href'].split('/')[-1])  ## okay, need to go figure out what indexing by -1 means in python... surely, it will be something a bit cute
#    with open(filename,'wb') as f:
#        f.write(requests.get(urljoin(url,link['href'])).content)

#do the analysis
add_all_events_from_pdf(colour_to_rainfall_mm,default_grid_links,default_station_indices,default_allowed_shift)        



