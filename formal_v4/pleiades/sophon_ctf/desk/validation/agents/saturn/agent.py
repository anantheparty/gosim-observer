import os, sys
os.environ["SOPHON_DIVE_OBJECT"] = 'saturn'
sys.path.insert(0, '/home/shu/kamico/observer/work/pkgs/sophon3')
import agent
agent.main()
